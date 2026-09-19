"""
staging_service.py
Royal Metal Allocation System — Python port

Ports StagingService.gs's submission workflow (scope resolution itself lives
in scope_service.py). A submission is ONE SHOT: once an operator submits for
a date, that party is locked for that date until an administrator saves it
(CLAUDE.md's two-stage workflow, stage 1).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date as date_, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from rmas.config import get_settings
from rmas.models.staging import RecordType, StagingRequirement, StagingStatus
from rmas.repository import allocation_repo, flow_repo, idempotency_repo, lock_repo, sector_repo, staging_repo
from rmas.rules.business_rules import BUSINESS_RULES
from rmas.schemas.staging import (
    OperatorAllocationLineOut,
    OperatorFlowLineOut,
    OperatorRequirementOut,
    OperatorTotalsOut,
    StagedRequirementsOut,
    StagedSubmissionOut,
    StagedValueOut,
    SubmitRequirementRequest,
    SubmitRequirementResultOut,
)
from rmas.schemas.common import PartyOut
from rmas.services import audit_service
from rmas.services.date_service import app_timezone, format_display_date, previous_source_date
from rmas.services.dto import AllocationLine, AllocationModel, FlowLine, StagingSubmissionSummary
from rmas.services.exceptions import ConflictError, ScopeError
from rmas.services.scope_service import UserScope, scope_allows, scope_allows_flow
from rmas.services.validation_service import assert_valid_weight, fmt3, round3

_settings = get_settings()


def _display_name(email: str) -> str:
    """Legacy getDisplayName_() fallback half (the config-map half now lives
    on the User row itself; this only covers the local-part fallback)."""
    local = email.split("@")[0].replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return " ".join(p.capitalize() for p in local.split()) or email


def get_operator_requirement_for_date(
    db: Session, scope: UserScope, selected_date: date_
) -> OperatorRequirementOut:
    if not scope.is_admin and not scope.parties:
        raise ScopeError(
            "No party is assigned to your account. Contact the administrator.",
            code="NO_PARTY_ASSIGNED",
        )

    prev_key = previous_source_date(selected_date)
    saved_alloc = allocation_repo.get_for_date(db, selected_date)
    saved_flow = flow_repo.get_for_date(db, selected_date)
    prev_alloc = allocation_repo.get_for_date(db, prev_key)
    prev_flow = flow_repo.get_for_date(db, prev_key)
    is_finalised = bool(saved_alloc)

    staging_rows = [
        r for r in staging_repo.list_for_date(db, selected_date)
        if scope_allows(scope, r.party.party_key if r.party else None)
    ]
    staged_by_key = {(r.record_type, r.sector_key): r for r in staging_rows}
    submitted = [r for r in staging_rows if r.status == StagingStatus.SUBMITTED]
    consumed = [r for r in staging_rows if r.status == StagingStatus.CONSUMED]
    is_submitted = len(submitted) > 0
    submission_meta = submitted[0] if submitted else (consumed[0] if consumed else None)

    allocation_sectors = [
        d for d in sector_repo.list_allocation_sectors(db)
        if scope_allows(scope, d.party.party_key if d.party else None)
    ]
    flow_sectors = [
        d for d in sector_repo.list_flow_sectors(db)
        if scope_allows_flow(scope, d.sector_key, d.party.party_key if d.party else None)
    ]

    allocations: list[OperatorAllocationLineOut] = []
    for d in allocation_sectors:
        saved = saved_alloc.get(d.sector_key) if is_finalised else None
        carried = prev_alloc.get(d.sector_key)
        staged = staged_by_key.get((RecordType.ALLOCATION, d.sector_key))
        previous_requirement = (
            saved.previous_requirement if saved else (round3(carried.balance) if carried else Decimal("0"))
        )
        allocations.append(
            OperatorAllocationLineOut(
                priority=d.priority, party=d.party.party_name if d.party else "",
                sector=d.sector_name, purity=d.purity,
                previous_requirement=previous_requirement,
                today_required=saved.today_required if saved else (staged.value if staged else Decimal("0")),
                alloted=saved.alloted if saved else Decimal("0"),
                balance=saved.balance if saved else round3(previous_requirement),
                is_finalised=is_finalised,
            )
        )

    metal_flow: list[OperatorFlowLineOut] = []
    for d in flow_sectors:
        saved = saved_flow.get(d.sector_key)
        carried = prev_flow.get(d.sector_key)
        staged = staged_by_key.get((RecordType.FLOW, d.sector_key))
        metal_flow.append(
            OperatorFlowLineOut(
                sector=d.sector_name, party=d.party.party_name if d.party else "",
                previous_acquired=round3(carried.acquired) if carried else Decimal("0"),
                today_acquired=saved.acquired if saved else (staged.value if staged else Decimal("0")),
                is_finalised=is_finalised,
            )
        )

    total_required = sum((a.today_required for a in allocations), Decimal("0"))
    total_acquired = sum((f.today_acquired for f in metal_flow), Decimal("0"))

    if is_finalised:
        code, message = "FINALISED", "The administrator has finalised this date. These are the final figures."
    elif is_submitted:
        when = submission_meta.submitted_at.strftime("%d-%b-%Y %H:%M:%S") if submission_meta else ""
        code = "ALREADY_SUBMITTED"
        message = (
            f"Your requirement was submitted on {when} and is awaiting the administrator. "
            "It cannot be changed."
        )
    else:
        code, message = "OPEN", "Enter your requirement and acquired metal, then submit."

    return OperatorRequirementOut(
        selected_date=selected_date, selected_date_display=format_display_date(selected_date),
        previous_source_date=prev_key, previous_source_date_display=format_display_date(prev_key),
        role=scope.role, parties=[PartyOut(party_key=p.party_key, party_name=p.party_name) for p in scope.parties],
        allocations=allocations, metal_flow=metal_flow,
        is_submitted=is_submitted, is_finalised=is_finalised, read_only=is_submitted or is_finalised,
        submitted_at=submission_meta.submitted_at.strftime("%d-%b-%Y %H:%M:%S") if submission_meta else "",
        submitted_by=submission_meta.operator_email if submission_meta else "",
        submission_id=submission_meta.submission_id if submission_meta else "",
        totals=OperatorTotalsOut(total_required=round3(total_required), total_acquired=round3(total_acquired)),
        code=code, message=message,
    )


@dataclass
class _SubmissionTotals:
    total_required: Decimal
    total_acquired: Decimal


def _assert_submission_rules(
    allocations: list[tuple], metal_flow: list[tuple]
) -> _SubmissionTotals:
    """
    Legacy assertSubmissionRules_(). Deliberately much lighter than the
    administrator's save — the full-allocation rule belongs to the final
    save, not to a requirement submission.
    """
    total_required = round3(sum((a[1] for a in allocations), Decimal("0")))
    total_acquired = round3(sum((f[1] for f in metal_flow), Decimal("0")))

    from rmas.services.exceptions import ValidationError

    if not (total_acquired > 0):
        raise ValidationError("Enter Today's Acquired metal before submitting.", code="NO_ACQUIRED_METAL")
    if not (total_required > 0):
        raise ValidationError(
            "Enter Today's Required weight for at least one sector before submitting.", code="NO_REQUIREMENT"
        )
    if BUSINESS_RULES.operator_required_within_acquired and (total_required - total_acquired) > _settings.weight_epsilon:
        diff = fmt3(total_required - total_acquired)
        raise ValidationError(
            f"Today's Required ({fmt3(total_required)} kg) cannot exceed Today’s Acquired "
            f"({fmt3(total_acquired)} kg). Reduce the requirement by {diff} kg.",
            code="REQUIRED_EXCEEDS_ACQUIRED",
        )
    return _SubmissionTotals(total_required=total_required, total_acquired=total_acquired)


def submit_operator_requirements(
    db: Session, user_email: str, scope: UserScope, payload: SubmitRequirementRequest
) -> SubmitRequirementResultOut:
    from rmas.services.exceptions import DuplicateRequestError

    if idempotency_repo.is_active(db, payload.request_id, _settings.request_id_ttl_seconds):
        raise DuplicateRequestError(
            "This submission was already sent. Reload the date to confirm.", code="DUPLICATE_REQUEST"
        )

    if not scope.parties and not scope.is_admin:
        raise ScopeError(
            "No party is assigned to your account. Contact the administrator.", code="NO_PARTY_ASSIGNED"
        )
    if scope.is_admin:
        raise ScopeError(
            "Administrators finalise dates directly on the Daily Allocation screen "
            "rather than submitting requirements.",
            code="ADMIN_CANNOT_SUBMIT",
        )

    allocation_sectors = sector_repo.list_allocation_sectors(db)
    flow_sectors = sector_repo.list_flow_sectors(db)

    from rmas.services.validation_service import normalize_sector_key

    sent_alloc = {normalize_sector_key(a.sector): a for a in payload.allocations}
    sent_flow = {normalize_sector_key(f.sector): f for f in payload.metal_flow}

    my_alloc = [d for d in allocation_sectors if scope_allows(scope, d.party.party_key if d.party else None)]
    my_flow = [d for d in flow_sectors if scope_allows_flow(scope, d.sector_key, d.party.party_key if d.party else None)]

    if not my_alloc and not my_flow:
        raise ScopeError("No sectors are mapped to your party. Contact the administrator.", code="NO_SECTORS")

    allocations = [
        (d, assert_valid_weight(sent_alloc[d.sector_key].today_required if d.sector_key in sent_alloc else 0,
                                 f"Today's Required ({d.sector_name})"))
        for d in my_alloc
    ]
    metal_flow = [
        (d, assert_valid_weight(sent_flow[d.sector_key].today_acquired if d.sector_key in sent_flow else 0,
                                 f"Today's Acquired ({d.sector_name})"))
        for d in my_flow
    ]

    owned_alloc = {d.sector_key for d in my_alloc}
    owned_flow = {d.sector_key for d in my_flow}
    trespass = [k for k in sent_alloc if k not in owned_alloc] + [k for k in sent_flow if k not in owned_flow]
    if trespass:
        raise ScopeError(
            "The submission included sectors that do not belong to your party.", code="SECTOR_NOT_IN_SCOPE"
        )

    totals = _assert_submission_rules(allocations, metal_flow)

    lock_repo.acquire_date_lock(db, payload.selected_date, _settings.save_lock_timeout_seconds)
    idempotency_repo.reserve(db, payload.request_id)

    # Legacy re-checks both locks AFTER acquiring the script lock, and each
    # "blocked" outcome RETURNS (with its own audit row) rather than falling
    # into the generic failure handler. Ported the same way: a blocked
    # outcome commits its own audit entry and raises directly, so a later
    # rollback (in the except block below) can never erase it.
    if allocation_repo.exists_for_date(db, payload.selected_date):
        db.rollback()
        raise ConflictError(
            "The administrator has already finalised this date. It can no longer receive submissions.",
            code="DATE_ALREADY_FINALISED",
        )

    party_ids = [p.id for p in scope.parties]
    existing = staging_repo.list_submitted_for_date_and_parties(db, payload.selected_date, party_ids)
    if existing:
        audit_service.write_audit_entry(
            db,
            audit_service.AuditEntryInput(
                allocation_date=payload.selected_date,
                action_type=audit_service.AuditAction.BLOCKED_RESUBMISSION,
                revision_number=0, user_email=user_email,
                reason="Resubmission blocked. A submission already exists for this date and party.",
                status=audit_service.AuditStatus.BLOCKED, request_id=payload.request_id,
            ),
        )
        db.commit()
        raise ConflictError(
            "You have already submitted for this date. A submission cannot be changed once sent. "
            "Contact the administrator if a correction is needed.",
            code="ALREADY_SUBMITTED",
        )

    try:
        fallback_party = scope.parties[0] if scope.parties else None
        submission_id = f"SUB-{datetime.now(app_timezone()):%Y%m%d-%H%M%S}-{random.randint(1000, 9999)}"
        now = datetime.now(app_timezone())

        rows: list[StagingRequirement] = []
        for d, value in allocations:
            party = d.party or fallback_party
            rows.append(
                StagingRequirement(
                    submission_id=submission_id, allocation_date=payload.selected_date,
                    party_id=party.id, operator_email=user_email, submitted_at=now,
                    record_type=RecordType.ALLOCATION, sector_key=d.sector_key,
                    value=round3(value), status=StagingStatus.SUBMITTED,
                )
            )
        for d, value in metal_flow:
            party = d.party or fallback_party
            rows.append(
                StagingRequirement(
                    submission_id=submission_id, allocation_date=payload.selected_date,
                    party_id=party.id, operator_email=user_email, submitted_at=now,
                    record_type=RecordType.FLOW, sector_key=d.sector_key,
                    value=round3(value), status=StagingStatus.SUBMITTED,
                )
            )
        staging_repo.insert_rows(db, rows)

        party_names = ", ".join(p.party_name for p in scope.parties)
        audit_service.write_audit_entry(
            db,
            audit_service.AuditEntryInput(
                allocation_date=payload.selected_date,
                action_type=audit_service.AuditAction.SUBMIT_REQUIREMENT,
                revision_number=0, user_email=user_email,
                reason=(
                    f"Operator requirement submitted for {party_names}. "
                    f"Required {fmt3(totals.total_required)} kg, acquired {fmt3(totals.total_acquired)} kg."
                ),
                updated_allocation=[{"s": d.sector_name, "tr": str(round3(v))} for d, v in allocations],
                updated_flow=[{"s": d.sector_name, "ac": str(round3(v))} for d, v in metal_flow],
                status=audit_service.AuditStatus.SUCCESS, request_id=payload.request_id,
            ),
        )

        db.commit()
        return SubmitRequirementResultOut(
            submission_id=submission_id, selected_date=payload.selected_date,
            allocation_records=len(allocations), flow_records=len(metal_flow),
            totals=OperatorTotalsOut(total_required=totals.total_required, total_acquired=totals.total_acquired),
        )
    except Exception as exc:
        # Rolling back also undoes the idempotency reservation made above
        # (never committed), which is exactly the legacy cache.remove(cacheKey)
        # behaviour: "allow a corrected retry" with the same request_id.
        db.rollback()
        try:
            audit_service.write_audit_entry(
                db,
                audit_service.AuditEntryInput(
                    allocation_date=payload.selected_date,
                    action_type=audit_service.AuditAction.FAILED_SUBMISSION,
                    revision_number=0, user_email=user_email,
                    reason=str(getattr(exc, "message", exc)),
                    status=audit_service.AuditStatus.FAILED, request_id=payload.request_id,
                ),
            )
            db.commit()
        except Exception:  # noqa: BLE001 — never mask the original error
            db.rollback()
        raise


def get_staged_requirements_for_date(
    db: Session, is_admin: bool, selected_date: date_
) -> StagedRequirementsOut:
    if not is_admin:
        raise ScopeError("Only an administrator can view submitted requirements.", code="NOT_AUTHORIZED")

    rows = staging_repo.list_for_date(db, selected_date)
    allocation_sectors = sector_repo.list_allocation_sectors(db)
    flow_sectors = sector_repo.list_flow_sectors(db)
    parties = sector_repo.list_parties(db)

    allocation_by_sector: dict[str, Decimal] = {}
    flow_by_sector: dict[str, Decimal] = {}
    for r in rows:
        if r.record_type == RecordType.ALLOCATION:
            allocation_by_sector[r.sector_key] = r.value
        else:
            flow_by_sector[r.sector_key] = r.value

    by_operator: dict[str, dict] = {}
    for r in rows:
        key = f"{r.operator_email.lower()}::{r.submission_id}"
        entry = by_operator.setdefault(key, {
            "party": "", "operator_email": r.operator_email, "operator_name": _display_name(r.operator_email),
            "submitted_at": r.submitted_at.strftime("%d-%b-%Y %H:%M:%S"), "submission_id": r.submission_id,
            "status": r.status.value, "total_required": Decimal("0"), "total_acquired": Decimal("0"),
        })
        if not entry["party"] and r.party:
            entry["party"] = r.party.party_name
        if r.record_type == RecordType.ALLOCATION:
            entry["total_required"] += r.value
        else:
            entry["total_acquired"] += r.value

    submissions = []
    for entry in by_operator.values():
        if not entry["party"]:
            entry["party"] = entry["operator_name"]
        submissions.append(
            StagedSubmissionOut(
                party=entry["party"], operator_email=entry["operator_email"], operator_name=entry["operator_name"],
                submitted_at=entry["submitted_at"], submission_id=entry["submission_id"], status=entry["status"],
                total_required=round3(entry["total_required"]), total_acquired=round3(entry["total_acquired"]),
            )
        )

    submitted_party_keys = {s.party.strip().lower() for s in submissions}
    pending_parties = [p.party_name for p in parties if p.party_key not in submitted_party_keys]

    total_required = sum((s.total_required for s in submissions), Decimal("0"))
    total_acquired = sum((s.total_acquired for s in submissions), Decimal("0"))

    return StagedRequirementsOut(
        selected_date=selected_date, selected_date_display=format_display_date(selected_date),
        submissions=submissions, pending_parties=pending_parties,
        allocation_values=[
            StagedValueOut(
                sector=d.sector_name, party=d.party.party_name if d.party else "",
                value=allocation_by_sector.get(d.sector_key, Decimal("0")),
                has_submission=d.sector_key in allocation_by_sector,
            )
            for d in allocation_sectors
        ],
        flow_values=[
            StagedValueOut(
                sector=d.sector_name, party=d.party.party_name if d.party else "",
                value=flow_by_sector.get(d.sector_key, Decimal("0")),
                has_submission=d.sector_key in flow_by_sector,
            )
            for d in flow_sectors
        ],
        totals=OperatorTotalsOut(total_required=round3(total_required), total_acquired=round3(total_acquired)),
    )


def mark_consumed(db: Session, selected_date: date_) -> int:
    """Legacy markStagingConsumed_(). Never raises — see audit_service.write_audit_entry
    for the same "must not block a completed save" principle."""
    try:
        return staging_repo.mark_consumed(db, selected_date)
    except Exception:  # noqa: BLE001
        return 0


def apply_staging_to_model(
    db: Session, model: AllocationModel, scope: UserScope, selected_date: date_
) -> None:
    """
    Legacy applyStagingToModel_(). For an OPERATOR: their submitted figures
    are shown back to them and every input is locked (one-shot). For an
    ADMIN: submitted figures are pulled in as editable starting values.
    """
    model.is_submitted = False
    if model.is_saved:
        return

    rows = [r for r in staging_repo.list_for_date(db, selected_date) if r.status == StagingStatus.SUBMITTED]
    if not rows:
        return

    visible = rows if scope.unrestricted else [
        r for r in rows
        if (
            scope_allows_flow(scope, r.sector_key, r.party.party_key if r.party else None)
            if r.record_type == RecordType.FLOW
            else scope_allows(scope, r.party.party_key if r.party else None)
        )
    ]
    if not visible:
        return

    alloc_by_key = {r.sector_key: r.value for r in visible if r.record_type == RecordType.ALLOCATION}
    flow_by_key = {r.sector_key: r.value for r in visible if r.record_type == RecordType.FLOW}

    for a in model.allocations:
        if a.sector_key in alloc_by_key:
            a.today_required = round3(alloc_by_key[a.sector_key])
            a.balance = round3(a.previous_requirement + a.today_required - a.alloted)
            a.from_submission = True
    for f in model.metal_flow:
        if f.sector_key in flow_by_key:
            f.today_acquired = round3(flow_by_key[f.sector_key])
            f.from_submission = True

    by_operator: dict[str, dict] = {}
    for r in visible:
        key = f"{r.operator_email.lower()}::{r.submission_id}"
        entry = by_operator.setdefault(key, {
            "party": "", "operator_email": r.operator_email, "operator_name": _display_name(r.operator_email),
            "submitted_at": r.submitted_at.strftime("%d-%b-%Y %H:%M:%S"), "submission_id": r.submission_id,
            "total_required": Decimal("0"), "total_acquired": Decimal("0"),
        })
        if not entry["party"] and r.party:
            entry["party"] = r.party.party_name
        if r.record_type == RecordType.ALLOCATION:
            entry["total_required"] += r.value
        else:
            entry["total_acquired"] += r.value

    model.staging_submissions = []
    for entry in by_operator.values():
        if not entry["party"]:
            entry["party"] = entry["operator_name"]
        model.staging_submissions.append(
            StagingSubmissionSummary(
                party=entry["party"], operator_email=entry["operator_email"], operator_name=entry["operator_name"],
                submitted_at=entry["submitted_at"], submission_id=entry["submission_id"],
                total_required=round3(entry["total_required"]), total_acquired=round3(entry["total_acquired"]),
            )
        )

    _recompute_scoped_totals(model)

    if not scope.unrestricted:
        model.is_submitted = True
        model.read_only = True
        model.can_edit_required = False
        model.can_edit_acquired = False
        model.can_edit_alloted = False
        first = model.staging_submissions[0] if model.staging_submissions else None
        model.submitted_at = first.submitted_at if first else ""
        model.submitted_by = first.operator_name if first else ""


def _recompute_scoped_totals(model: AllocationModel) -> None:
    """Legacy recomputeScopedTotals_()."""
    from rmas.services.validation_service import compute_totals

    model.totals = compute_totals(model.allocations, model.metal_flow)
    if model.show_global_totals is False:
        model.totals.remaining_to_allocate = Decimal("0")
    model.total_previous_acquired = round3(sum((f.previous_acquired for f in model.metal_flow), Decimal("0")))
