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
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.allocation import MetalMaster
from models.flow import MetalFlowMaster
from repository import allocation_repo, flow_repo, idempotency_repo, staging_repo
from repository.sector_repo import (
    get_all_sectors,
    get_allocation_sectors,
    get_flow_sectors,
)
from rules.business_rules import business_rules
from services import audit_service
from services.audit_service import AuditEntry
from services import cascade_service
from services.date_service import (
    format_display_date,
    previous_source_date,
    resolve_source_date,
)
from services.exceptions import (
    DateAlreadySavedError,
    DateNotSavedError,
    DuplicateRequestError,
    NotAuthorizedError,
    RevisionDisabledError,
    RevisionFailedError,
    RmasError,
)
from services.scope_service import UserScope, is_administrator
from services.validation_service import (
    Totals,
    assert_revision_reason,
    assert_save_rules,
    compute_totals,
    validate_and_normalize_payload,
)


logger = logging.getLogger(__name__)


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
    # True when this figure came from an operator submission rather than the
    # saved ledger, so the screen can mark it as somebody else's input.
    from_submission: bool = False


@dataclass
class FlowRow:
    flow_sector_id: int
    sector_name: str
    party_name: str
    previous_acquired_g: int
    today_acquired_g: int
    from_submission: bool = False


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
    # Filled in by staging_service.apply_staging_to_model(), not here — the
    # allocation service must not depend on the staging service.
    already_submitted: bool = False
    staged_value_count: int = 0


def _resolve_source_date(
    db: Session, repo, selected: date, rule_date: date
) -> tuple[str | None, bool]:
    """Which date the carried figures come from, and whether it is the fallback.

    A thin adapter over date_service.resolve_source_date, which is THE rule and
    is shared with the forward cascade. It used to live here, which meant the
    screen and the cascade could only agree by being written twice and kept in
    step by hand. `rule_date` is still accepted so callers read unchanged, but
    the shared function derives it.
    """
    source = resolve_source_date(
        selected,
        date_exists=lambda iso: repo.date_exists(db, iso),
        latest_date_before=lambda iso: repo.latest_date_before(db, iso),
    )
    return source.source_date, source.used_fallback


def carried_balances(db: Session, selected: date) -> dict[int, int]:
    """Each sector's previous requirement for `selected`: the source date's balance.

    The server derives this; it is never accepted from the client. A sector with
    no row on the source date carries zero, never a value from an earlier date.
    """
    source, _ = _resolve_source_date(
        db, allocation_repo, selected, previous_source_date(selected)
    )
    if not source:
        return {}
    return {
        row.sector_id: row.balance_g
        for row in allocation_repo.get_rows_for_date(db, source)
    }


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


def _failure_reason(exc: Exception) -> str:
    """An RmasError carries a message written for a person; anything else does not."""
    text = exc.message if isinstance(exc, RmasError) else str(exc)
    return text[:1000] or "Unknown failure"


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
            # Derived from the source date, never taken from the payload.
            carried_g=carried_balances(db, selected),
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

        # 4b. Operator submissions for this date stop being pending. Ports
        # markStagingConsumed_(): date-wide, not per party, and the rows are
        # marked rather than deleted so the record of what was submitted
        # survives. Never allowed to fail the save — a bookkeeping problem must
        # not reverse a committed ledger.
        try:
            staging_repo.mark_consumed(db, date_iso)
        except Exception:  # noqa: BLE001 — deliberately swallowed, as in legacy
            logger.exception("staging consume failed for %s", date_iso)

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

    except (DuplicateRequestError, NotAuthorizedError, DateAlreadySavedError):
        # Already handled above: either deliberately unaudited, or audited and
        # committed on its own branch.
        raise

    except Exception as exc:
        db.rollback()
        # Failures are audited too (CLAUDE.md rule 14), in their own transaction
        # so the rollback above cannot discard the record of what went wrong.
        #
        # This deliberately catches RmasError as well. It used to sit behind an
        # `except RmasError: raise`, so a ValidationError — the most common
        # failure there is — escaped with no audit row and no rollback, which
        # is precisely the case rule 14 exists for. Legacy audits every failure.
        audit_service.write_entry_safely(
            db,
            AuditEntry(
                allocation_date=date_iso,
                action_type=audit_service.ACTION_FAILED_SAVE,
                action_status=audit_service.STATUS_FAILED,
                user_email=user.email,
                reason=_failure_reason(exc),
                request_id=request_id,
            ),
        )
        db.commit()
        raise


# --------------------------------------------------------------- revision


@dataclass
class CascadedDate:
    allocation_date: date
    audit_id: str
    sectors_changed: int
    negative_balance_sectors: int


@dataclass
class RevisionResult:
    allocation_date: date
    revision_number: int
    allocation_records: int
    flow_records: int
    audit_id: str
    request_id: str
    totals: Totals
    cascaded: list[CascadedDate]


@dataclass
class CascadePreview:
    date_count: int
    sector_count: int
    negative_balance_dates: list[date]


@dataclass
class _FlowSnapshotRow:
    """snapshot_flow() reads .sector_name and .today_acquired_g; the ORM row
    carries no name, so the stored rows are adapted here."""

    sector_name: str
    today_acquired_g: int


@dataclass
class _AllocSnapshotRow:
    """What snapshot_allocations() reads.

    A stored MetalMaster row carries the historical priority and purity but not
    the sector NAME, and a cascade's recomputed LedgerRow carries none of the
    three — so both are adapted here rather than the snapshot being taught
    about two more shapes.
    """

    sector_name: str
    priority: str
    purity: str
    previous_requirement_g: int
    today_required_g: int
    alloted_g: int
    balance_g: int


def _sector_names(db: Session) -> dict[int, str]:
    return {sector.sector_id: sector.sector_name for sector in get_all_sectors(db)}


def _stored_allocation_snapshot(db: Session, date_iso: str) -> str:
    """The allocation ledger for one date, exactly as stored, named for the log."""
    names = _sector_names(db)
    return audit_service.snapshot_allocations(
        [
            _AllocSnapshotRow(
                sector_name=names.get(row.sector_id, str(row.sector_id)),
                priority=row.priority_snapshot,
                purity=row.purity_snapshot,
                previous_requirement_g=row.previous_requirement_g,
                today_required_g=row.today_required_g,
                alloted_g=row.alloted_g,
                balance_g=row.balance_g,
            )
            for row in allocation_repo.get_rows_for_date(db, date_iso)
        ]
    )


def _recalculated_snapshot(db: Session, date_iso: str, rows_after) -> str:
    """The post-cascade state of one date.

    The recomputed rows carry only figures, so the historical priority and
    purity are taken from the stored rows — the cascade never changes them, and
    substituting today's sector definitions into a historical record would be
    quietly wrong.
    """
    names = _sector_names(db)
    stored = {row.sector_id: row for row in allocation_repo.get_rows_for_date(db, date_iso)}
    snapshot_rows = []
    for row in rows_after:
        origin = stored.get(row.sector_id)
        snapshot_rows.append(
            _AllocSnapshotRow(
                sector_name=names.get(row.sector_id, str(row.sector_id)),
                priority=origin.priority_snapshot if origin else "",
                purity=origin.purity_snapshot if origin else "",
                previous_requirement_g=row.previous_requirement_g,
                today_required_g=row.today_required_g,
                alloted_g=row.alloted_g,
                balance_g=row.balance_g,
            )
        )
    return audit_service.snapshot_allocations(snapshot_rows)


def _ledger_rows(rows) -> tuple[cascade_service.LedgerRow, ...]:
    return tuple(
        cascade_service.LedgerRow(
            sector_id=row.sector_id,
            previous_requirement_g=row.previous_requirement_g,
            today_required_g=row.today_required_g,
            alloted_g=row.alloted_g,
            balance_g=row.balance_g,
        )
        for row in rows
    )


def _stored_flow_snapshot(db: Session, scope: UserScope, date_iso: str) -> str:
    """The flow ledger as stored, named for the snapshot."""
    names = {
        flow_sector.flow_sector_id: flow_sector.sector_name
        for flow_sector, _party in get_flow_sectors(db, scope)
    }
    rows = [
        _FlowSnapshotRow(
            names.get(row.flow_sector_id, str(row.flow_sector_id)), row.acquired_g
        )
        for row in flow_repo.get_rows_for_date(db, date_iso)
    ]
    return audit_service.snapshot_flow(rows)


def _plan_cascade(
    db: Session, selected: date, edited_rows
) -> cascade_service.CascadeResult:
    """Work out which later dates the revision moves. Reads only.

    UNSCOPED on purpose: a later date's correctness is a property of the ledger,
    not of who happens to be looking at it. Going through the scoped sector
    reader would silently skip rows the acting admin cannot see and leave the
    ledger inconsistent.
    """
    date_iso = selected.isoformat()
    later_dates = allocation_repo.saved_dates_after(db, date_iso)

    by_date: dict[str, list] = {iso: [] for iso in later_dates}
    for row in allocation_repo.get_rows_for_dates(db, later_dates):
        by_date[row.allocation_date].append(row)

    return cascade_service.cascade_forward(
        edited_date=date_iso,
        edited_rows=_ledger_rows(edited_rows),
        later_ledgers=[
            cascade_service.DateLedger(iso, _ledger_rows(by_date[iso]))
            for iso in later_dates
        ],
        saved_dates=allocation_repo.all_saved_dates(db),
    )


def _assert_may_revise(
    db: Session, *, user, selected: date, request_id: str | None
) -> None:
    """Guards 1 and 2, in legacy's order.

    The feature flag first, because a disabled feature is not an authorisation
    failure and legacy audits nothing for it. Then the administrator check,
    which DOES write a blocked entry — the UI flag is never trusted, and an
    attempt to revise without authorisation is exactly what rule 14 wants
    recorded. A preview passes request_id=None and is never audited: it is a
    read, and auditing it would let anyone flood the log by clicking.
    """
    if not business_rules.allow_admin_revision:
        raise RevisionDisabledError(
            "REVISION_DISABLED",
            "Saved dates are currently immutable. Revision is disabled.",
        )

    if not is_administrator(user):
        if request_id is not None:
            audit_service.write_entry(
                db,
                AuditEntry(
                    allocation_date=selected.isoformat(),
                    action_type=audit_service.ACTION_UNAUTHORIZED_REVISION,
                    action_status=audit_service.STATUS_BLOCKED,
                    user_email=user.email,
                    reason="Revision attempted without administrator authorization.",
                    request_id=request_id,
                ),
            )
            db.commit()
        raise NotAuthorizedError(
            "NOT_AUTHORIZED",
            "You are not authorized to revise a saved date. Contact an administrator.",
        )


def _validate_revision(db: Session, scope: UserScope, selected: date, allocations, flow):
    """Guards 3-4 and 6, shared by the preview and the commit, so the screen can
    never preview something the commit would refuse."""
    normalized = validate_and_normalize_payload(
        allocations,
        flow,
        get_allocation_sectors(db, scope),
        get_flow_sectors(db, scope),
        # Derived from the source date, never accepted from the payload.
        carried_g=carried_balances(db, selected),
    )
    assert_save_rules(normalized.totals)

    if not allocation_repo.date_exists(db, selected.isoformat()):
        raise DateNotSavedError(
            "DATE_NOT_SAVED",
            "This date has not been saved yet, so there is nothing to revise. "
            "Use Save Current Data instead.",
        )
    return normalized


def preview_revision(
    db: Session,
    *,
    user,
    scope: UserScope,
    selected: date,
    submitted_allocations,
    submitted_flow,
    revision_reason: str,
) -> CascadePreview:
    """How much a revision would rewrite, without committing anything."""
    _assert_may_revise(db, user=user, selected=selected, request_id=None)
    assert_revision_reason(revision_reason)
    normalized = _validate_revision(
        db, scope, selected, submitted_allocations, submitted_flow
    )

    cascade = _plan_cascade(db, selected, normalized.allocations)
    # Nothing was written — cascade_forward is pure — but roll back anyway so a
    # preview can never leave a dirty session for the next request.
    db.rollback()

    return CascadePreview(
        date_count=len(cascade.recalculated),
        sector_count=cascade.sector_count,
        negative_balance_dates=[
            date.fromisoformat(iso) for iso in cascade.negative_balance_dates
        ],
    )


def revise_daily_allocation(
    db: Session,
    *,
    user,
    scope: UserScope,
    selected: date,
    submitted_allocations,
    submitted_flow,
    revision_reason: str,
    request_id: str,
) -> RevisionResult:
    """Replace a saved date's figures and carry the change forward.

    Ports reviseDailyAllocation(), plus the forward cascade legacy never had —
    legacy rewrote only the selected date, leaving every later saved date
    carrying a previous_requirement derived from the old balance.

    Guard order follows legacy exactly:
      0.  idempotency. A double-clicked revise would otherwise write two
          revisions and two sets of cascade entries; unlike save, there is no
          date_exists check afterwards to catch it.
      1.  ALLOW_ADMIN_REVISION
      2.  administrator check, audited as UNAUTHORIZED_REVISION
      3.  revision reason, minimum 10 characters
      4.  validate against the live definitions, then the save rules
      5.  (legacy took a 30s script lock here — see save_daily_allocation)
      6.  DATE_NOT_SAVED
      7.  revision number = latest for this date + 1
      8.  audit ids allocated before anything is written

    ATOMIC. The edited date, every cascaded date and all of their audit entries
    commit together or not at all: audit_service.write_entry only flushes, so
    the single db.commit() at the end covers the lot. The ledger can never be
    left half-cascaded, and the log can never record a cascade that did not
    happen. That replaces legacy's delete-then-restore dance, which could itself
    fail and leave REVISION_RESTORE_FAILED behind.
    """
    date_iso = selected.isoformat()
    audit_id: str | None = None
    revision_number = 0
    before_alloc = ""
    before_flow = ""

    if idempotency_repo.find_live_entry(db, request_id) is not None:
        raise DuplicateRequestError(
            "DUPLICATE_REQUEST",
            "This revision was already submitted. Reload the date to confirm the result.",
        )

    _assert_may_revise(db, user=user, selected=selected, request_id=request_id)

    try:
        reason = assert_revision_reason(revision_reason)
        normalized = _validate_revision(
            db, scope, selected, submitted_allocations, submitted_flow
        )

        revision_number = audit_service.get_latest_revision_number(db, date_iso) + 1
        before_alloc = _stored_allocation_snapshot(db, date_iso)
        before_flow = _stored_flow_snapshot(db, scope, date_iso)

        cascade = _plan_cascade(db, selected, normalized.allocations)

        # Ids for the parent and every cascade entry, allocated up front: no two
        # entries in this transaction can then collide, and a failure part-way
        # through still has the parent id to record against.
        audit_id, *cascade_ids = audit_service.generate_audit_ids(
            1 + len(cascade.recalculated)
        )

        # The edited date is REPLACED — its sector set can legitimately differ
        # from what was saved, because the payload was rebuilt from the live
        # definitions. Delete before insert: both helpers only flush(), so the
        # other order trips uq_master_date_sector.
        allocation_repo.delete_rows_for_date(db, date_iso)
        flow_repo.delete_rows_for_date(db, date_iso)
        allocation_records = allocation_repo.insert_rows(
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
                    revision_number=revision_number,
                    saved_by=user.email,
                )
                for row in normalized.allocations
            ],
        )
        flow_records = flow_repo.insert_rows(
            db,
            [
                MetalFlowMaster(
                    allocation_date=date_iso,
                    flow_sector_id=row.flow_sector_id,
                    party_id=row.party_id,
                    acquired_g=row.today_acquired_g,
                    revision_number=revision_number,
                    saved_by=user.email,
                )
                for row in normalized.metal_flow
            ],
        )

        # Later dates are UPDATED in place — see apply_recalculation for why.
        cascaded: list[CascadedDate] = []
        for entry, cascade_audit_id in zip(
            cascade.recalculated, cascade_ids, strict=True
        ):
            cascaded_revision = (
                audit_service.get_latest_revision_number(db, entry.allocation_date) + 1
            )
            before_snapshot = _stored_allocation_snapshot(db, entry.allocation_date)
            after_snapshot = _recalculated_snapshot(
                db, entry.allocation_date, entry.rows_after
            )
            allocation_repo.apply_recalculation(
                db,
                entry.allocation_date,
                {
                    change.sector_id: (
                        change.previous_requirement_g,
                        change.balance_g,
                    )
                    for change in entry.changes
                },
                revision_number=cascaded_revision,
            )
            audit_service.write_entry(
                db,
                AuditEntry(
                    audit_id=cascade_audit_id,
                    allocation_date=entry.allocation_date,
                    action_type=audit_service.ACTION_RECALCULATE,
                    action_status=audit_service.STATUS_SUCCESS,
                    user_email=user.email,
                    revision_number=cascaded_revision,
                    reason=(
                        "Recalculated after revision of "
                        f"{format_display_date(selected)}."
                    ),
                    previous_allocation_data=before_snapshot,
                    updated_allocation_data=after_snapshot,
                    # Metal Flow has no balance column, so the cascade never
                    # touches it. The flow snapshots are omitted rather than
                    # written identically, so the detail view skips the flow
                    # table instead of rendering a no-change one as noise.
                    request_id=request_id,
                    parent_audit_id=audit_id,
                ),
            )
            cascaded.append(
                CascadedDate(
                    allocation_date=date.fromisoformat(entry.allocation_date),
                    audit_id=cascade_audit_id,
                    sectors_changed=len(entry.changes),
                    negative_balance_sectors=len(entry.negative_balance_sector_ids),
                )
            )

        audit_service.write_entry(
            db,
            AuditEntry(
                audit_id=audit_id,
                allocation_date=date_iso,
                action_type=audit_service.ACTION_REVISE,
                action_status=audit_service.STATUS_SUCCESS,
                user_email=user.email,
                revision_number=revision_number,
                reason=reason,
                previous_allocation_data=before_alloc,
                updated_allocation_data=audit_service.snapshot_allocations(
                    normalized.allocations
                ),
                previous_metal_flow_data=before_flow,
                updated_metal_flow_data=audit_service.snapshot_flow(
                    normalized.metal_flow
                ),
                request_id=request_id,
            ),
        )

        result = RevisionResult(
            allocation_date=selected,
            revision_number=revision_number,
            allocation_records=allocation_records,
            flow_records=flow_records,
            audit_id=audit_id,
            request_id=request_id,
            totals=normalized.totals,
            cascaded=cascaded,
        )

        idempotency_repo.prune_expired(db)
        idempotency_repo.record(
            db,
            request_id,
            user.email,
            "POST /allocations/revise",
            _serialise_result(
                SaveResult(
                    allocation_date=selected,
                    allocation_records=allocation_records,
                    flow_records=flow_records,
                    audit_id=audit_id,
                    request_id=request_id,
                    totals=normalized.totals,
                )
            ),
        )
        db.commit()
        return result

    except (DuplicateRequestError, NotAuthorizedError, RevisionDisabledError):
        # Already handled: deliberately unaudited, or audited and committed on
        # its own branch above.
        raise

    except Exception as exc:
        db.rollback()
        # EVERY failure is audited, validation included. Legacy's single catch
        # does the same, and rule 14 is explicit that failed attempts are logged
        # too. Written in its own transaction so the rollback above cannot
        # discard the record of what went wrong.
        audit_service.write_entry_safely(
            db,
            AuditEntry(
                audit_id=audit_id,
                allocation_date=date_iso,
                action_type=audit_service.ACTION_FAILED_REVISION,
                action_status=audit_service.STATUS_FAILED,
                user_email=user.email,
                revision_number=revision_number,
                reason=_failure_reason(exc),
                previous_allocation_data=before_alloc,
                previous_metal_flow_data=before_flow,
                request_id=request_id,
            ),
        )
        db.commit()
        if isinstance(exc, RmasError):
            raise
        raise RevisionFailedError(
            "REVISION_FAILED",
            "The revision could not be completed. Nothing was changed.",
        ) from exc
