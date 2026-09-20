"""
services/allocation_service.py
Royal Metal Allocation System — Python port of Code.gs + DataService.gs's
buildAllocationModel_().

Assembles the Daily Allocation screen for a date: the sector list the caller may
see, what each sector's previous requirement is (carried forward), and what has
been entered or saved.

THE CARRY-FORWARD RULE (CLAUDE.md section 6, rules 4-5):
  * The "rule date" is Saturday if the selected date is a Monday, otherwise the
    previous calendar day — the six-day working week.
  * If nothing was saved on the rule date and CARRY_FORWARD_FROM_LATEST_SAVED is
    on, fall back to the most recent saved date before the selected one, so a
    gap of skipped days never wipes out a carried balance.
  * A sector's previous_requirement is the source row's BALANCE, not its
    previous_requirement — yesterday's closing balance is today's opening
    demand.
  * The allocation and flow ledgers resolve their source dates INDEPENDENTLY.

All weights are integer grams (schema.sql). Nothing here touches float.
"""

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.allocation import MetalMaster
from models.flow import MetalFlowMaster
from repository import allocation_repo, flow_repo, idempotency_repo
from repository.sector_repo import get_allocation_sectors, get_flow_sectors
from rules.business_rules import business_rules
from services import audit_service
from services.audit_service import AuditEntry
from services.date_service import format_display_date, previous_source_date
from services.exceptions import (
    DateAlreadySavedError,
    DuplicateRequestError,
    NotAuthorizedError,
    RmasError,
)
from services.scope_service import UserScope, is_administrator
from services.validation_service import (
    Totals,
    assert_save_rules,
    compute_totals,
    validate_and_normalize_payload,
)


@dataclass
class AllocationRow:
    sector_id: int
    sector_name: str
    priority: str
    purity: str
    party_name: str
    previous_requirement_g: int
    today_required_g: int
    alloted_g: int
    balance_g: int


@dataclass
class FlowRow:
    flow_sector_id: int
    sector_name: str
    party_name: str
    previous_acquired_g: int
    today_acquired_g: int


@dataclass
class AllocationModel:
    selected_date: date
    selected_date_display: str
    rule_source_date: date
    rule_source_date_display: str
    # The date the figures actually came from, which may be older than the rule
    # date when the fallback kicked in. This is what the screen labels
    # "Previous Source Date" — legacy shows the real source, not the theory.
    previous_source_date: date | None
    previous_source_date_display: str
    used_fallback_source: bool
    has_previous_data: bool
    is_saved: bool
    allocations: list[AllocationRow]
    metal_flow: list[FlowRow]
    totals: Totals
    total_previous_acquired_g: int


def _resolve_source_date(
    db: Session, repo, selected: date, rule_date: date
) -> tuple[str | None, bool]:
    """Which date the carried figures come from, and whether it is the fallback.

    Returns (source_date_iso, used_fallback).
    """
    rule_iso = rule_date.isoformat()
    if repo.date_exists(db, rule_iso):
        return rule_iso, False

    if not business_rules.carry_forward_from_latest_saved:
        return None, False

    fallback = repo.latest_date_before(db, selected.isoformat())
    return fallback, fallback is not None


def build_allocation_model(db: Session, selected: date, scope: UserScope) -> AllocationModel:
    """Ports buildAllocationModel_(), scoped to what this user may see."""
    rule_date = previous_source_date(selected)
    selected_iso = selected.isoformat()

    alloc_source, alloc_fallback = _resolve_source_date(
        db, allocation_repo, selected, rule_date
    )
    flow_source, flow_fallback = _resolve_source_date(db, flow_repo, selected, rule_date)

    saved_alloc = {r.sector_id: r for r in allocation_repo.get_rows_for_date(db, selected_iso)}
    saved_flow = {r.flow_sector_id: r for r in flow_repo.get_rows_for_date(db, selected_iso)}
    is_saved = bool(saved_alloc)

    carried_alloc = (
        {r.sector_id: r for r in allocation_repo.get_rows_for_date(db, alloc_source)}
        if alloc_source
        else {}
    )
    carried_flow = (
        {r.flow_sector_id: r for r in flow_repo.get_rows_for_date(db, flow_source)}
        if flow_source
        else {}
    )

    allocations = []
    for sector, party in get_allocation_sectors(db, scope):
        saved = saved_alloc.get(sector.sector_id)
        carried = carried_alloc.get(sector.sector_id)

        if saved is not None:
            previous_requirement_g = saved.previous_requirement_g
            today_required_g = saved.today_required_g
            alloted_g = saved.alloted_g
            balance_g = saved.balance_g
        else:
            # Yesterday's closing BALANCE becomes today's previous requirement.
            previous_requirement_g = carried.balance_g if carried else 0
            today_required_g = 0
            alloted_g = 0
            # With nothing entered yet, the balance is just what was carried in.
            balance_g = previous_requirement_g

        allocations.append(
            AllocationRow(
                sector_id=sector.sector_id,
                sector_name=sector.sector_name,
                priority=sector.priority,
                purity=sector.purity,
                party_name=party.party_name,
                previous_requirement_g=previous_requirement_g,
                today_required_g=today_required_g,
                alloted_g=alloted_g,
                balance_g=balance_g,
            )
        )

    metal_flow = []
    for flow_sector, party in get_flow_sectors(db, scope):
        saved = saved_flow.get(flow_sector.flow_sector_id)
        carried = carried_flow.get(flow_sector.flow_sector_id)
        metal_flow.append(
            FlowRow(
                flow_sector_id=flow_sector.flow_sector_id,
                sector_name=flow_sector.sector_name,
                party_name=party.party_name,
                previous_acquired_g=carried.acquired_g if carried else 0,
                today_acquired_g=saved.acquired_g if saved else 0,
            )
        )

    totals = compute_totals(allocations, metal_flow)
    shown_source = alloc_source or flow_source or rule_date.isoformat()

    return AllocationModel(
        selected_date=selected,
        selected_date_display=format_display_date(selected),
        rule_source_date=rule_date,
        rule_source_date_display=format_display_date(rule_date),
        previous_source_date=date.fromisoformat(shown_source),
        previous_source_date_display=format_display_date(date.fromisoformat(shown_source)),
        used_fallback_source=alloc_fallback or flow_fallback,
        has_previous_data=bool(alloc_source or flow_source),
        is_saved=is_saved,
        allocations=allocations,
        metal_flow=metal_flow,
        totals=totals,
        total_previous_acquired_g=sum(f.previous_acquired_g for f in metal_flow),
    )


# ---------------------------------------------------------------------------
# Save — the admin commit. Ports Code.gs's saveDailyAllocation().
# ---------------------------------------------------------------------------


@dataclass
class SaveResult:
    allocation_date: date
    allocation_records: int
    flow_records: int
    audit_id: str
    request_id: str
    totals: Totals


def _serialise_result(result: SaveResult) -> str:
    return json.dumps(
        {
            "allocation_date": result.allocation_date.isoformat(),
            "allocation_records": result.allocation_records,
            "flow_records": result.flow_records,
            "audit_id": result.audit_id,
            "request_id": result.request_id,
        }
    )


def save_daily_allocation(
    db: Session,
    *,
    user,
    scope: UserScope,
    selected: date,
    submitted_allocations,
    submitted_flow,
    request_id: str,
) -> SaveResult:
    """Commit a date. Administrators only; operators submit requirements instead.

    Order of operations follows legacy exactly (Code.gs:236-350):
      0.  idempotency guard
      0b. administrator check
      1.  validate against the LIVE sector definitions, then the save rules
      2.  (legacy took a 30s global script lock here — see the note below)
      3.  re-check that the date is not already saved
      4.  write both ledgers
      5.  audit the result

    CONCURRENCY. Legacy serialised every write in the whole script with a single
    30-second lock. Here the guarantee comes from two stronger, cheaper things:
    SQLite takes an exclusive write lock for the duration of the transaction, so
    saves are already serialised; and `UNIQUE (allocation_date, sector_id)` makes
    a double-save impossible even if two writers somehow interleaved — the loser
    gets an IntegrityError, which is translated to DATE_ALREADY_SAVED below.
    There is deliberately no hand-rolled lock: SQLite has neither advisory locks
    nor SELECT ... FOR UPDATE, and pretending otherwise would be theatre.
    **On a move to PostgreSQL, add an advisory lock keyed on the allocation date**
    (CLAUDE.md section 6, rule 11), because Postgres allows concurrent writers
    that SQLite does not.
    """
    date_iso = selected.isoformat()

    # 0. Double-click / retry protection.
    existing = idempotency_repo.find_live_entry(db, request_id)
    if existing is not None:
        raise DuplicateRequestError(
            "DUPLICATE_REQUEST",
            "This save request was already submitted. Reload the date to confirm the result.",
        )

    # 0b. Only administrators may finalise a date.
    if not is_administrator(user):
        raise NotAuthorizedError(
            "NOT_AUTHORIZED",
            "Only an administrator can save a date. Submit your requirement instead.",
        )

    try:
        # 1. Rebuild from the live definitions; the client supplies only weights.
        normalized = validate_and_normalize_payload(
            submitted_allocations,
            submitted_flow,
            get_allocation_sectors(db, scope),
            get_flow_sectors(db, scope),
        )
        assert_save_rules(normalized.totals)

        # 3. A saved date is immutable — revise it instead.
        if allocation_repo.date_exists(db, date_iso):
            audit_service.write_entry(
                db,
                AuditEntry(
                    allocation_date=date_iso,
                    action_type=audit_service.ACTION_BLOCKED_DUPLICATE,
                    action_status=audit_service.STATUS_BLOCKED,
                    user_email=user.email,
                    reason="Duplicate save attempt blocked.",
                    request_id=request_id,
                ),
            )
            db.commit()
            raise DateAlreadySavedError(
                "DATE_ALREADY_SAVED",
                "Data already saved. This date is locked and cannot be saved again.",
            )

        # 4. Write both ledgers.
        allocation_repo.insert_rows(
            db,
            [
                MetalMaster(
                    allocation_date=date_iso,
                    sector_id=row.sector_id,
                    party_id=row.party_id,
                    priority_snapshot=row.priority,
                    purity_snapshot=row.purity,
                    previous_requirement_g=row.previous_requirement_g,
                    today_required_g=row.today_required_g,
                    alloted_g=row.alloted_g,
                    balance_g=row.balance_g,
                    revision_number=0,
                    saved_by=user.email,
                )
                for row in normalized.allocations
            ],
        )
        flow_repo.insert_rows(
            db,
            [
                MetalFlowMaster(
                    allocation_date=date_iso,
                    flow_sector_id=row.flow_sector_id,
                    party_id=row.party_id,
                    acquired_g=row.today_acquired_g,
                    revision_number=0,
                    saved_by=user.email,
                )
                for row in normalized.metal_flow
            ],
        )

        # 5. Audit the successful save.
        audit_id = audit_service.write_entry(
            db,
            AuditEntry(
                allocation_date=date_iso,
                action_type=audit_service.ACTION_SAVE,
                action_status=audit_service.STATUS_SUCCESS,
                user_email=user.email,
                revision_number=0,
                reason="Initial daily allocation save.",
                previous_allocation_data="",
                updated_allocation_data=audit_service.snapshot_allocations(
                    normalized.allocations
                ),
                previous_metal_flow_data="",
                updated_metal_flow_data=audit_service.snapshot_flow(normalized.metal_flow),
                request_id=request_id,
            ),
        )

        result = SaveResult(
            allocation_date=selected,
            allocation_records=len(normalized.allocations),
            flow_records=len(normalized.metal_flow),
            audit_id=audit_id,
            request_id=request_id,
            totals=normalized.totals,
        )

        idempotency_repo.prune_expired(db)
        idempotency_repo.record(
            db, request_id, user.email, "POST /allocations", _serialise_result(result)
        )
        db.commit()
        return result

    except IntegrityError as exc:
        # UNIQUE(allocation_date, sector_id) — another writer won the race.
        db.rollback()
        raise DateAlreadySavedError(
            "DATE_ALREADY_SAVED",
            "Data already saved. This date is locked and cannot be saved again.",
        ) from exc

    except RmasError:
        raise

    except Exception as exc:
        db.rollback()
        # Failures are audited too (CLAUDE.md rule 14), in their own transaction
        # so the rollback above cannot discard the record of what went wrong.
        audit_service.write_entry_safely(
            db,
            AuditEntry(
                allocation_date=date_iso,
                action_type=audit_service.ACTION_FAILED_SAVE,
                action_status=audit_service.STATUS_FAILED,
                user_email=user.email,
                reason=str(exc)[:1000] or "Unknown failure",
                request_id=request_id,
            ),
        )
        db.commit()
        raise
