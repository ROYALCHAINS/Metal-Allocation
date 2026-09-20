"""
services/staging_service.py
Royal Metal Allocation System — Python port of StagingService.gs

Stage 1 of the two-stage daily workflow: an operator submits what their party
needs and what arrived. Nothing here writes to the masters — only the
administrator's save does (CLAUDE.md section 1).

A SUBMISSION IS ONE SHOT. Once a party has submitted for a date it cannot
submit again, and the operator's inputs lock. Corrections go through the
administrator.

Validation is deliberately lighter than the admin save: the full-allocation
rules belong to the final commit, not to a requirement submission.
"""

import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from models.staging import MetalRequirementStaging
from repository import allocation_repo, idempotency_repo, staging_repo
from repository.sector_repo import get_allocation_sectors, get_flow_sectors
from rules.business_rules import business_rules
from services import audit_service
from services.audit_service import AuditEntry
from services.date_service import APP_TIMEZONE
from services.exceptions import (
    DuplicateRequestError,
    NotAuthorizedError,
    ScopeError,
    ValidationError,
)
from services.scope_service import UserScope, is_administrator
from services.validation_service import assert_valid_weight
from services.weight_service import grams_to_kg


def generate_submission_id() -> str:
    """Ports legacy's 'SUB-yyyyMMdd-HHmmss-NNNN'."""
    stamp = datetime.now(ZoneInfo(APP_TIMEZONE)).strftime("%Y%m%d-%H%M%S")
    return f"SUB-{stamp}-{random.randint(1000, 9999)}"


@dataclass
class SubmissionResult:
    allocation_date: date
    submission_id: str
    allocation_records: int
    flow_records: int
    total_required_g: int
    total_acquired_g: int
    audit_id: str


@dataclass
class StagedRow:
    sector_id: int
    sector_name: str
    party_id: int
    value_g: int


@dataclass
class SubmissionState:
    """What the Daily Allocation screen needs to decide what is editable."""

    already_submitted: bool = False
    staged_value_count: int = 0
    submissions: list = field(default_factory=list)


def _assert_submission_rules(total_required_g: int, total_acquired_g: int) -> None:
    """Ports assertSubmissionRules_().

    Only two rules bite in production. The third,
    OPERATOR_REQUIRED_WITHIN_ACQUIRED, is a deliberately-disabled toggle
    (CLAUDE.md section 6) — requirement is NOT capped by supply, because demand
    legitimately exceeds supply and the shortfall carries forward as balance.
    """
    if total_acquired_g <= 0:
        raise ValidationError(
            "NO_ACQUIRED_METAL", "Enter Today’s Acquired metal before submitting."
        )
    if total_required_g <= 0:
        raise ValidationError(
            "NO_REQUIREMENT",
            "Enter Today’s Required weight for at least one sector before submitting.",
        )
    if (
        business_rules.operator_required_within_acquired
        and total_required_g > total_acquired_g
    ):
        short = grams_to_kg(total_required_g - total_acquired_g)
        raise ValidationError(
            "REQUIRED_EXCEEDS_ACQUIRED",
            f"Today’s Required ({grams_to_kg(total_required_g)} kg) cannot exceed "
            f"Today’s Acquired ({grams_to_kg(total_acquired_g)} kg). "
            f"Reduce the requirement by {short} kg.",
        )


def apply_staging_to_model(db: Session, model, scope: UserScope, selected: date):
    """Overlay pending submissions onto the Daily Allocation model.

    Ports applyStagingToModel_(). This is how an operator's figures reach the
    administrator's screen: the operator writes to staging, and the admin reads
    the same date with those values already in the fields, ready to allocate
    against and save.

    THE MASTERS WIN ONCE SAVED. A saved date returns untouched — staging is a
    proposal, and the committed ledger is the fact.

    A sector with no staged row keeps its carried-forward value. A staged value
    of ZERO still overlays: "the party needs nothing today" is a statement, not
    an absence, so presence is tested rather than truthiness.
    """
    state = SubmissionState()
    if model.is_saved:
        return state

    staged_allocation = staging_repo.staged_allocation_values(
        db, selected.isoformat(), scope
    )
    staged_flow = staging_repo.staged_flow_values(db, selected.isoformat(), scope)
    if not staged_allocation and not staged_flow:
        return state

    applied = 0
    for row in model.allocations:
        if row.sector_id in staged_allocation:
            row.today_required_g = staged_allocation[row.sector_id]
            row.balance_g = (
                row.previous_requirement_g + row.today_required_g - row.alloted_g
            )
            row.from_submission = True
            applied += 1

    for row in model.metal_flow:
        if row.flow_sector_id in staged_flow:
            row.today_acquired_g = staged_flow[row.flow_sector_id]
            row.from_submission = True
            applied += 1

    state.staged_value_count = applied
    state.submissions = staging_repo.submission_summary(db, selected.isoformat(), scope)
    # An operator who has submitted sees their own figures, locked.
    state.already_submitted = bool(
        not scope.unrestricted
        and staging_repo.any_rows_for_parties(db, selected.isoformat(), scope.party_ids)
    )
    return state


def submit_requirements(
    db: Session,
    *,
    user,
    scope: UserScope,
    selected: date,
    submitted_allocations,
    submitted_flow,
    request_id: str,
) -> SubmissionResult:
    """Record one operator submission. Order of checks follows legacy exactly.

    The record set is rebuilt from the LIVE sector definitions, so the client
    cannot introduce a sector it does not own — it supplies weights only, keyed
    by id. Every in-scope sector produces a row, defaulting to zero, so the
    submission is a complete statement of the party's position rather than a
    sparse patch.
    """
    date_iso = selected.isoformat()
    # Captured before any rollback. A rollback expires every ORM instance, so
    # reading user.email afterwards would re-query inside a dead transaction —
    # and the failure audit below runs precisely on that path.
    operator_email = user.email

    # 1. Double-click / retry protection.
    if idempotency_repo.find_live_entry(db, request_id) is not None:
        raise DuplicateRequestError(
            "DUPLICATE_REQUEST",
            "This submission was already sent. Reload the date to confirm.",
        )

    # 2. An administrator finalises dates directly; they never submit.
    if is_administrator(user):
        raise NotAuthorizedError(
            "ADMIN_CANNOT_SUBMIT",
            "Administrators finalise dates directly on the Daily Allocation screen "
            "rather than submitting requirements.",
        )

    # 3. No party means no submission — and it fails closed.
    if not scope.party_ids:
        raise ScopeError(
            "NO_PARTY_ASSIGNED",
            "No party is assigned to your account. Contact the administrator.",
        )

    owned_allocation = get_allocation_sectors(db, scope)
    owned_flow = get_flow_sectors(db, scope)
    if not owned_allocation and not owned_flow:
        raise ScopeError(
            "NO_SECTORS", "No sectors are mapped to your party. Contact the administrator."
        )

    sent_allocation = {row.sector_id: row.today_required_kg for row in submitted_allocations}
    sent_flow = {row.flow_sector_id: row.today_acquired_kg for row in submitted_flow}

    try:
        # 4. Validate every value against the sectors actually owned.
        allocation_rows: list[StagedRow] = []
        for sector, party in owned_allocation:
            grams = assert_valid_weight(
                sent_allocation.get(sector.sector_id, 0),
                f"Today’s Required ({sector.sector_name})",
            )
            allocation_rows.append(
                StagedRow(sector.sector_id, sector.sector_name, party.party_id, grams)
            )

        flow_rows: list[StagedRow] = []
        for flow_sector, party in owned_flow:
            grams = assert_valid_weight(
                sent_flow.get(flow_sector.flow_sector_id, 0),
                f"Today’s Acquired ({flow_sector.sector_name})",
            )
            flow_rows.append(
                StagedRow(
                    flow_sector.flow_sector_id,
                    flow_sector.sector_name,
                    party.party_id,
                    grams,
                )
            )

        # 5. Anything sent that the operator does not own is a trespass, not a
        #    silent drop — say so rather than quietly discarding their input.
        owned_allocation_ids = {s.sector_id for s, _ in owned_allocation}
        owned_flow_ids = {f.flow_sector_id for f, _ in owned_flow}
        if set(sent_allocation) - owned_allocation_ids or set(sent_flow) - owned_flow_ids:
            raise ScopeError(
                "SECTOR_NOT_IN_SCOPE",
                "The submission included sectors that do not belong to your party.",
            )

        total_required_g = sum(r.value_g for r in allocation_rows)
        total_acquired_g = sum(r.value_g for r in flow_rows)
        _assert_submission_rules(total_required_g, total_acquired_g)

        # 6. A finalised date takes no more submissions. No audit entry —
        #    legacy returns this one plainly.
        if allocation_repo.date_exists(db, date_iso):
            raise ValidationError(
                "DATE_ALREADY_FINALISED",
                "The administrator has already finalised this date. "
                "It can no longer receive submissions.",
            )

        # 7. One shot per party per date. Checked at ANY status, so a committed
        #    date stays closed.
        if staging_repo.any_rows_for_parties(db, date_iso, scope.party_ids):
            audit_service.write_entry(
                db,
                AuditEntry(
                    allocation_date=date_iso,
                    action_type=audit_service.ACTION_BLOCKED_RESUBMISSION,
                    action_status=audit_service.STATUS_BLOCKED,
                    user_email=operator_email,
                    reason=(
                        "Resubmission blocked. A submission already exists for this "
                        "date and party."
                    ),
                    request_id=request_id,
                ),
            )
            db.commit()
            raise ValidationError(
                "ALREADY_SUBMITTED",
                "You have already submitted for this date. A submission cannot be "
                "changed once sent. Contact the administrator if a correction is needed.",
            )

        submission_id = generate_submission_id()
        rows = [
            MetalRequirementStaging(
                submission_id=submission_id,
                allocation_date=date_iso,
                party_id=row.party_id,
                operator_email=user.email,
                record_type=record_type,
                sector_id=row.sector_id if record_type == "ALLOCATION" else None,
                flow_sector_id=row.sector_id if record_type == "FLOW" else None,
                value_g=row.value_g,
                status="SUBMITTED",
            )
            for record_type, source in (("ALLOCATION", allocation_rows), ("FLOW", flow_rows))
            for row in source
        ]
        staging_repo.insert_rows(db, rows)

        audit_id = audit_service.write_entry(
            db,
            AuditEntry(
                allocation_date=date_iso,
                action_type=audit_service.ACTION_SUBMIT_REQUIREMENT,
                action_status=audit_service.STATUS_SUCCESS,
                user_email=operator_email,
                reason=(
                    f"Operator requirement submitted. Required "
                    f"{grams_to_kg(total_required_g)} kg, acquired "
                    f"{grams_to_kg(total_acquired_g)} kg."
                ),
                # Compact keys, matching the audit snapshot format.
                updated_allocation_data=json.dumps(
                    [
                        {"s": r.sector_name, "tr": str(grams_to_kg(r.value_g))}
                        for r in allocation_rows
                    ]
                ),
                updated_metal_flow_data=json.dumps(
                    [
                        {"s": r.sector_name, "ac": str(grams_to_kg(r.value_g))}
                        for r in flow_rows
                    ]
                ),
                request_id=request_id,
            ),
        )
        idempotency_repo.record(
            db,
            request_id,
            user_email=operator_email,
            endpoint="submit_requirements",
            response_json=json.dumps(
                {
                    "submission_id": submission_id,
                    "allocation_records": len(allocation_rows),
                    "flow_records": len(flow_rows),
                }
            ),
        )
        db.commit()

    except (ValidationError, ScopeError) as exc:
        db.rollback()
        # Every thrown validation is audited as a failed attempt — the log
        # answers "what was attempted", not merely "what happened" (rule 14).
        if exc.code not in ("ALREADY_SUBMITTED",):
            audit_service.write_entry_safely(
                db,
                AuditEntry(
                    allocation_date=date_iso,
                    action_type=audit_service.ACTION_FAILED_SUBMISSION,
                    action_status=audit_service.STATUS_FAILED,
                    user_email=operator_email,
                    reason=exc.message,
                    request_id=request_id,
                ),
            )
            db.commit()
        raise

    return SubmissionResult(
        allocation_date=selected,
        submission_id=submission_id,
        allocation_records=len(allocation_rows),
        flow_records=len(flow_rows),
        total_required_g=total_required_g,
        total_acquired_g=total_acquired_g,
        audit_id=audit_id,
    )
