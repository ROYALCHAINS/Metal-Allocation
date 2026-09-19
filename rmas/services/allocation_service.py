"""
allocation_service.py
Royal Metal Allocation System — Python port

Ports Code.gs (web app entry points, save/revise) and DataService.gs's
buildAllocationModel_ / buildMasterRowValues_ / buildFlowRowValues_ /
appendBothMasters_. This is the highest-risk file in the port: locking,
idempotency, transactionality and the audit trail all meet here.

TRANSACTION BOUNDARIES — read before changing this file.
Legacy Sheets writes are immediate and un-transactional, so a "rollback" of
a partially-completed save was a manual compensating delete, while the audit
write for a blocked/failed attempt was a separate, always-persisted
operation. Postgres gives real transactions, which is used here to get an
equivalent-or-better guarantee, but it means commit points matter:
  * A "blocked" outcome (date already saved) commits its own audit row and
    raises immediately — never inside a block that a later rollback could
    unwind.
  * The success path builds everything (row inserts + consumed-staging
    update + the SUCCESS audit row) in one transaction and commits once.
  * Any other exception rolls back the whole attempt (which also undoes the
    idempotency-key reservation, exactly matching legacy's
    `cache.remove(cacheKey)` "allow a corrected retry" behaviour) and then
    writes a FAILED_* audit row in a fresh commit, never masking the
    original error.
"""

from __future__ import annotations

from datetime import date as date_
from decimal import Decimal

from sqlalchemy.orm import Session

from rmas.config import get_settings
from rmas.models.allocation import AllocationRecord
from rmas.models.flow import FlowRecord
from rmas.models.user import User, UserRole
from rmas.repository import allocation_repo, flow_repo, idempotency_repo, lock_repo, sector_repo
from rmas.rules.business_rules import BUSINESS_RULES, SECTOR_EXPECTATIONS
from rmas.schemas.allocation import (
    AllocationLineOut,
    AllocationModelOut,
    AllocationSectorOut,
    BootstrapConfigOut,
    BootstrapOut,
    DateAlreadySavedOut,
    FlowLineOut,
    FlowSectorOut,
    ReviseAllocationRequest,
    ReviseResultOut,
    SaveAllocationRequest,
    SaveResultOut,
    StagingSubmissionSummaryOut,
    TotalsOut,
)
from rmas.schemas.auth import CurrentUserOut
from rmas.schemas.common import PartyOut
from rmas.services import audit_service, staging_service
from rmas.services.date_service import format_display_date, previous_source_date
from rmas.services.dto import AllocationLine, AllocationModel, FlowLine
from rmas.services.exceptions import ConflictError, DuplicateRequestError, ScopeError, ValidationError
from rmas.services.scope_service import (
    UserScope,
    apply_scope_to_allocation_model,
    scoped_allocation_sectors,
    scoped_flow_sectors,
)
from rmas.services.validation_service import (
    Totals,
    assert_save_rules,
    assert_signed_weight,
    assert_valid_weight,
    compute_totals,
    normalize_sector_key,
    round3,
)

_settings = get_settings()


def get_public_config() -> BootstrapConfigOut:
    """Legacy getPublicConfig_() — never includes admin emails."""
    return BootstrapConfigOut(
        app_name=_settings.app_name,
        app_version=_settings.app_version,
        decimals=_settings.weight_decimals,
        expected_allocation_rows=SECTOR_EXPECTATIONS.allocation_rows,
        expected_flow_rows=SECTOR_EXPECTATIONS.flow_rows,
        require_full_allocation=BUSINESS_RULES.require_full_allocation,
        require_positive_acquired=BUSINESS_RULES.require_positive_acquired,
        min_revision_reason_length=BUSINESS_RULES.min_revision_reason_length,
    )


def get_bootstrap_data(db: Session, scope: UserScope) -> BootstrapOut:
    """Legacy getAppBootstrapData()."""
    from rmas.services.date_service import today

    allocation_sectors = scoped_allocation_sectors(db, scope)
    flow_sectors = scoped_flow_sectors(db, scope)

    return BootstrapOut(
        config=get_public_config(),
        access=CurrentUserOut(email=scope.email, display_name=scope.display_name, is_admin=scope.is_admin, role=scope.role),
        time_zone=_settings.app_timezone,
        today=today(),
        parties=[PartyOut(party_key=p.party_key, party_name=p.party_name) for p in scope.parties],
        role=scope.role,
        allocation_sectors=[
            AllocationSectorOut(priority=d.priority, party=d.party.party_name if d.party else "", sector=d.sector_name, purity=d.purity)
            for d in allocation_sectors
        ],
        flow_sectors=[
            FlowSectorOut(sector=d.sector_name, party=d.party.party_name if d.party else "") for d in flow_sectors
        ],
    )


def check_date_already_saved(db: Session, selected_date: date_) -> DateAlreadySavedOut:
    """Legacy checkDateAlreadySaved()."""
    return DateAlreadySavedOut(selected_date=selected_date, is_saved=allocation_repo.exists_for_date(db, selected_date))


def build_allocation_model(db: Session, selected_date: date_) -> AllocationModel:
    """
    Legacy buildAllocationModel_(). Saved dates load their stored values;
    unsaved dates load previous-source-date carry-forward values with empty
    inputs.
    """
    allocation_sectors = sector_repo.list_allocation_sectors(db)
    flow_sectors = sector_repo.list_flow_sectors(db)
    parties = sector_repo.list_parties(db)

    rule_key = previous_source_date(selected_date)

    saved_alloc = allocation_repo.get_for_date(db, selected_date)
    saved_flow = flow_repo.get_for_date(db, selected_date)
    is_saved = bool(saved_alloc)

    # The rule date is Monday -> Saturday, otherwise the previous calendar
    # day. When nothing was saved on that exact date, fall back to the most
    # recent saved date STRICTLY BEFORE THE SELECTED DATE (not before the
    # rule date) if CARRY_FORWARD_FROM_LATEST_SAVED is on, so a gap of
    # skipped days never wipes out the carried-forward balance.
    alloc_rule_rows = allocation_repo.get_for_date(db, rule_key)
    if alloc_rule_rows:
        alloc_source_key: date_ | None = rule_key
        prev_alloc = alloc_rule_rows
    elif BUSINESS_RULES.carry_forward_from_latest_saved:
        alloc_source_key = allocation_repo.latest_date_before(db, selected_date)
        prev_alloc = allocation_repo.get_for_date(db, alloc_source_key) if alloc_source_key else {}
    else:
        alloc_source_key = None
        prev_alloc = {}

    flow_rule_rows = flow_repo.get_for_date(db, rule_key)
    if flow_rule_rows:
        flow_source_key: date_ | None = rule_key
        prev_flow = flow_rule_rows
    elif BUSINESS_RULES.carry_forward_from_latest_saved:
        flow_source_key = flow_repo.latest_date_before(db, selected_date)
        prev_flow = flow_repo.get_for_date(db, flow_source_key) if flow_source_key else {}
    else:
        flow_source_key = None
        prev_flow = {}

    has_previous_data = bool(alloc_source_key or flow_source_key)
    used_fallback = bool(
        (alloc_source_key and alloc_source_key != rule_key) or (flow_source_key and flow_source_key != rule_key)
    )

    allocations: list[AllocationLine] = []
    for d in allocation_sectors:
        saved = saved_alloc.get(d.sector_key) if is_saved else None
        carried = prev_alloc.get(d.sector_key)
        previous_requirement = (
            saved.previous_requirement if saved else (round3(carried.balance) if carried else Decimal("0"))
        )
        allocations.append(
            AllocationLine(
                priority=d.priority, party=d.party.party_name if d.party else "",
                party_key=d.party.party_key if d.party else "",
                sector=d.sector_name, sector_key=d.sector_key, purity=d.purity,
                previous_requirement=previous_requirement,
                today_required=saved.today_required if saved else Decimal("0"),
                alloted=saved.alloted if saved else Decimal("0"),
                balance=saved.balance if saved else round3(previous_requirement),
            )
        )

    metal_flow: list[FlowLine] = []
    for d in flow_sectors:
        saved = saved_flow.get(d.sector_key)
        carried = prev_flow.get(d.sector_key)
        metal_flow.append(
            FlowLine(
                sector=d.sector_name, sector_key=d.sector_key, party=d.party.party_name if d.party else "",
                party_key=d.party.party_key if d.party else "",
                previous_acquired=round3(carried.acquired) if carried else Decimal("0"),
                today_acquired=saved.acquired if saved else Decimal("0"),
            )
        )

    totals = compute_totals(allocations, metal_flow)
    total_previous_acquired = round3(sum((f.previous_acquired for f in metal_flow), Decimal("0")))

    return AllocationModel(
        selected_date=selected_date,
        previous_source_date=alloc_source_key or flow_source_key or rule_key,
        rule_source_date=rule_key,
        allocation_source_date=alloc_source_key,
        flow_source_date=flow_source_key,
        used_fallback_source=used_fallback,
        has_previous_data=has_previous_data,
        is_saved=is_saved,
        saved_record_count=len(saved_alloc),
        saved_flow_record_count=len(saved_flow),
        allocations=allocations,
        metal_flow=metal_flow,
        parties=parties,
        totals=totals,
        total_previous_acquired=total_previous_acquired,
    )


def get_allocation_for_date(db: Session, user: User, scope: UserScope, selected_date: date_) -> AllocationModelOut:
    """Legacy getAllocationForDate()."""
    model = build_allocation_model(db, selected_date)
    is_admin = scope.is_admin

    if not is_admin and not scope.parties:
        raise ScopeError(
            "No party is assigned to your account. Contact the administrator.", code="NO_PARTY_ASSIGNED"
        )

    apply_scope_to_allocation_model(model, scope)
    staging_service.apply_staging_to_model(db, model, scope, selected_date)

    # Set AFTER the staging overlay, exactly as legacy Code.gs recomputes
    # these two flags right after applyStagingToModel_ runs — the staging
    # overlay's own read_only=True (for an operator's own submission) is
    # subsumed by this, since !is_admin is already true for every operator.
    model.read_only = model.is_saved or not is_admin
    model.can_revise = model.is_saved and is_admin and BUSINESS_RULES.allow_admin_revision

    if model.is_saved:
        code, message = "DATE_ALREADY_SAVED", "Data Already Saved. This date is locked and cannot be saved again."
    elif model.is_submitted:
        when = f" on {model.submitted_at}" if model.submitted_at else ""
        code = "REQUIREMENT_SUBMITTED"
        message = f"Your requirement was submitted{when} and is awaiting the administrator. It cannot be changed."
    elif model.staging_submissions:
        code = "SUBMISSIONS_RECEIVED"
        message = (
            f"{len(model.staging_submissions)} operator submission(s) loaded into this date. "
            "Adjust the figures, allocate, then save."
        )
    elif model.has_previous_data:
        code = "OK"
        message = (
            f"No records exist for {format_display_date(model.rule_source_date)}. "
            f"Previous values carried forward from {format_display_date(model.previous_source_date)}."
            if model.used_fallback_source
            else "Previous day values loaded."
        )
    else:
        code = "NO_PREVIOUS_DATA"
        message = f"No records found for {format_display_date(model.previous_source_date)}. Previous values are shown as 0.000."

    return _model_to_schema(model, scope, code, message)


def _model_to_schema(model: AllocationModel, scope: UserScope, code: str, message: str) -> AllocationModelOut:
    return AllocationModelOut(
        selected_date=model.selected_date, selected_date_display=format_display_date(model.selected_date),
        previous_source_date=model.previous_source_date,
        previous_source_date_display=format_display_date(model.previous_source_date),
        rule_source_date=model.rule_source_date, rule_source_date_display=format_display_date(model.rule_source_date),
        used_fallback_source=model.used_fallback_source, has_previous_data=model.has_previous_data,
        is_saved=model.is_saved, saved_record_count=model.saved_record_count,
        saved_flow_record_count=model.saved_flow_record_count,
        allocations=[
            AllocationLineOut(
                priority=a.priority, party=a.party, sector=a.sector, purity=a.purity,
                previous_requirement=a.previous_requirement, today_required=a.today_required,
                alloted=a.alloted, balance=a.balance, from_submission=a.from_submission,
            )
            for a in model.allocations
        ],
        metal_flow=[
            FlowLineOut(
                sector=f.sector, party=f.party, previous_acquired=f.previous_acquired,
                today_acquired=f.today_acquired, from_submission=f.from_submission,
            )
            for f in model.metal_flow
        ],
        parties=[PartyOut(party_key=p.party_key, party_name=p.party_name) for p in model.parties],
        totals=_totals_to_schema(model.totals), total_previous_acquired=model.total_previous_acquired,
        access=CurrentUserOut(email=scope.email, display_name=scope.display_name, is_admin=scope.is_admin, role=scope.role),
        role=model.role, is_operator=model.is_operator, read_only=model.read_only, can_revise=model.can_revise,
        can_edit_required=model.can_edit_required, can_edit_acquired=model.can_edit_acquired,
        can_edit_alloted=model.can_edit_alloted, show_global_totals=model.show_global_totals,
        is_submitted=model.is_submitted, submitted_at=model.submitted_at, submitted_by=model.submitted_by,
        staging_submissions=[
            StagingSubmissionSummaryOut(
                party=s.party, operator_email=s.operator_email, operator_name=s.operator_name,
                submitted_at=s.submitted_at, submission_id=s.submission_id,
                total_required=s.total_required, total_acquired=s.total_acquired,
            )
            for s in model.staging_submissions
        ],
        code=code, message=message,
    )


def _totals_to_schema(t: Totals) -> TotalsOut:
    return TotalsOut(
        total_previous_requirement=t.total_previous_requirement, total_today_required=t.total_today_required,
        total_alloted=t.total_alloted, total_balance=t.total_balance, total_acquired=t.total_acquired,
        remaining_to_allocate=t.remaining_to_allocate,
    )


class _NormalizedPayload:
    __slots__ = ("selected_date", "allocations", "metal_flow", "totals")

    def __init__(self, selected_date, allocations, metal_flow, totals):
        self.selected_date = selected_date
        self.allocations = allocations
        self.metal_flow = metal_flow
        self.totals = totals


def validate_and_normalize_payload(payload: SaveAllocationRequest, allocation_sectors, flow_sectors) -> _NormalizedPayload:
    """
    Legacy validateAndNormalizePayload_(). Authoritative priority/party/
    sector/purity ALWAYS come from the live sector definitions, never from
    the client payload — only previous_requirement/today_required/alloted/
    today_acquired are taken from the client, and even those are re-derived
    (balance is always server-computed, never trusted from the client).
    """
    if len(payload.allocations) != len(allocation_sectors):
        raise ValidationError(
            f"Expected {len(allocation_sectors)} allocation rows but received {len(payload.allocations)}.",
            code="ALLOCATION_ROW_COUNT",
        )
    if len(payload.metal_flow) != len(flow_sectors):
        raise ValidationError(
            f"Expected {len(flow_sectors)} Metal Flow rows but received {len(payload.metal_flow)}.",
            code="FLOW_ROW_COUNT",
        )

    alloc_by_key = {normalize_sector_key(r.sector): r for r in payload.allocations if normalize_sector_key(r.sector)}
    flow_by_key = {normalize_sector_key(r.sector): r for r in payload.metal_flow if normalize_sector_key(r.sector)}

    allocations: list[AllocationLine] = []
    for d in allocation_sectors:
        submitted = alloc_by_key.get(d.sector_key)
        if submitted is None:
            raise ValidationError(f'Allocation data for "{d.sector_name}" was not received.', code="SECTOR_MISSING")
        previous_requirement = assert_signed_weight(submitted.previous_requirement, f"Previous Requirement ({d.sector_name})")
        today_required = assert_valid_weight(submitted.today_required, f"Today's Required Weight ({d.sector_name})")
        alloted = assert_valid_weight(submitted.alloted, f"Alloted ({d.sector_name})")
        allocations.append(
            AllocationLine(
                priority=d.priority, party=d.party.party_name if d.party else "",
                party_key=d.party.party_key if d.party else "",
                sector=d.sector_name, sector_key=d.sector_key, purity=d.purity,
                previous_requirement=previous_requirement, today_required=today_required, alloted=alloted,
                balance=round3(previous_requirement + today_required - alloted),
            )
        )

    metal_flow: list[FlowLine] = []
    for d in flow_sectors:
        submitted = flow_by_key.get(d.sector_key)
        if submitted is None:
            raise ValidationError(f'Metal Flow data for "{d.sector_name}" was not received.', code="FLOW_SECTOR_MISSING")
        today_acquired = assert_valid_weight(submitted.today_acquired, f"Today's Acquired ({d.sector_name})")
        metal_flow.append(
            FlowLine(
                sector=d.sector_name, sector_key=d.sector_key, party=d.party.party_name if d.party else "",
                party_key=d.party.party_key if d.party else "",
                previous_acquired=Decimal("0"), today_acquired=today_acquired,
            )
        )

    totals = compute_totals(allocations, metal_flow)
    return _NormalizedPayload(payload.selected_date, allocations, metal_flow, totals)


def _stored_allocation_to_line(r: AllocationRecord) -> AllocationLine:
    """
    Adapts a persisted AllocationRecord (whose `.sector` is an ORM
    relationship, not a string) into the same AllocationLine shape
    audit_service.snapshot_allocations() expects — used only for building a
    revision's "before" snapshot from what is currently stored.
    """
    return AllocationLine(
        priority=r.priority, party=r.sector.party.party_name if r.sector.party else "",
        party_key=r.sector.party.party_key if r.sector.party else "",
        sector=r.sector.sector_name, sector_key=r.sector.sector_key, purity=r.purity,
        previous_requirement=r.previous_requirement, today_required=r.today_required,
        alloted=r.alloted, balance=r.balance,
    )


def _stored_flow_to_line(r: FlowRecord) -> FlowLine:
    return FlowLine(
        sector=r.flow_sector.sector_name, sector_key=r.flow_sector.sector_key,
        party=r.flow_sector.party.party_name if r.flow_sector.party else "",
        party_key=r.flow_sector.party.party_key if r.flow_sector.party else "",
        previous_acquired=Decimal("0"), today_acquired=r.acquired,
    )


def save_daily_allocation(db: Session, user: User, payload: SaveAllocationRequest) -> SaveResultOut:
    """Legacy saveDailyAllocation()."""
    request_id = payload.request_id or audit_service.generate_request_id()

    if idempotency_repo.is_active(db, request_id, _settings.request_id_ttl_seconds):
        raise DuplicateRequestError(
            "This save request was already submitted. Reload the date to confirm the result.",
            code="DUPLICATE_REQUEST",
        )
    if not (user.role == UserRole.ADMIN and not user.admin_denied):
        raise ScopeError("Only an administrator can save a date. Submit your requirement instead.", code="NOT_AUTHORIZED")

    allocation_sectors = sector_repo.list_allocation_sectors(db)
    flow_sectors = sector_repo.list_flow_sectors(db)
    normalized = validate_and_normalize_payload(payload, allocation_sectors, flow_sectors)
    assert_save_rules(normalized.totals, BUSINESS_RULES)

    lock_repo.acquire_date_lock(db, normalized.selected_date, _settings.save_lock_timeout_seconds)
    idempotency_repo.reserve(db, request_id)

    if allocation_repo.exists_for_date(db, normalized.selected_date):
        audit_service.write_audit_entry(
            db,
            audit_service.AuditEntryInput(
                allocation_date=normalized.selected_date, action_type=audit_service.AuditAction.BLOCKED_DUPLICATE,
                revision_number=0, user_email=user.email, reason="Duplicate save attempt blocked.",
                status=audit_service.AuditStatus.BLOCKED, request_id=request_id,
            ),
        )
        db.commit()
        raise ConflictError(
            "Data Already Saved. This date is locked and cannot be saved again. Select a new date.",
            code="DATE_ALREADY_SAVED",
        )

    try:
        sector_by_key = {s.sector_key: s for s in allocation_sectors}
        flow_by_key = {s.sector_key: s for s in flow_sectors}

        master_rows = [
            AllocationRecord(
                allocation_date=normalized.selected_date, sector_id=sector_by_key[a.sector_key].id,
                priority=a.priority, purity=a.purity, previous_requirement=a.previous_requirement,
                today_required=a.today_required, alloted=a.alloted, balance=a.balance,
            )
            for a in normalized.allocations
        ]
        flow_rows = [
            FlowRecord(
                flow_date=normalized.selected_date, flow_sector_id=flow_by_key[f.sector_key].id,
                acquired=f.today_acquired,
            )
            for f in normalized.metal_flow
        ]

        if len(master_rows) != SECTOR_EXPECTATIONS.allocation_rows or len(flow_rows) != SECTOR_EXPECTATIONS.flow_rows:
            raise ValidationError(
                "The prepared records did not match the expected counts. Nothing was saved.",
                code="ROW_COUNT_MISMATCH",
            )

        allocation_repo.insert_rows(db, master_rows)
        flow_repo.insert_rows(db, flow_rows)
        consumed_rows = staging_service.mark_consumed(db, normalized.selected_date)

        audit_id = audit_service.write_audit_entry(
            db,
            audit_service.AuditEntryInput(
                allocation_date=normalized.selected_date, action_type=audit_service.AuditAction.SAVE,
                revision_number=0, user_email=user.email, reason="Initial daily allocation save.",
                updated_allocation=audit_service.snapshot_allocations(normalized.allocations),
                updated_flow=audit_service.snapshot_flow(normalized.metal_flow),
                status=audit_service.AuditStatus.SUCCESS, request_id=request_id,
            ),
        )

        db.commit()
        return SaveResultOut(
            selected_date=normalized.selected_date, selected_date_display=format_display_date(normalized.selected_date),
            master_records=len(master_rows), flow_records=len(flow_rows), staging_rows_consumed=consumed_rows,
            totals=_totals_to_schema(normalized.totals), audit_id=audit_id, request_id=request_id,
        )
    except Exception as exc:
        db.rollback()  # also undoes the idempotency reservation — allows a corrected retry
        try:
            audit_service.write_audit_entry(
                db,
                audit_service.AuditEntryInput(
                    allocation_date=payload.selected_date, action_type=audit_service.AuditAction.FAILED_SAVE,
                    revision_number=0, user_email=user.email, reason=str(getattr(exc, "message", exc)),
                    status=audit_service.AuditStatus.FAILED, request_id=request_id,
                ),
            )
            db.commit()
        except Exception:  # noqa: BLE001 — never mask the original error
            db.rollback()
        raise


def revise_daily_allocation(db: Session, user: User, payload: ReviseAllocationRequest) -> ReviseResultOut:
    """Legacy reviseDailyAllocation()."""
    request_id = payload.request_id or audit_service.generate_request_id()

    if not BUSINESS_RULES.allow_admin_revision:
        raise ScopeError("Saved dates are currently immutable. Revision is disabled.", code="REVISION_DISABLED")

    if not (user.role == UserRole.ADMIN and not user.admin_denied):
        audit_service.write_audit_entry(
            db,
            audit_service.AuditEntryInput(
                allocation_date=payload.selected_date, action_type=audit_service.AuditAction.UNAUTHORIZED_REVISION,
                revision_number=0, user_email=user.email,
                reason="Revision attempted without administrator authorization.",
                status=audit_service.AuditStatus.BLOCKED, request_id=request_id,
            ),
        )
        db.commit()
        raise ScopeError("You are not authorized to revise a saved date. Contact an administrator.", code="NOT_AUTHORIZED")

    from rmas.services.validation_service import assert_revision_reason

    reason = assert_revision_reason(payload.revision_reason, BUSINESS_RULES)

    allocation_sectors = sector_repo.list_allocation_sectors(db)
    flow_sectors = sector_repo.list_flow_sectors(db)
    normalized = validate_and_normalize_payload(payload, allocation_sectors, flow_sectors)
    assert_save_rules(normalized.totals, BUSINESS_RULES)

    lock_repo.acquire_date_lock(db, normalized.selected_date, _settings.save_lock_timeout_seconds)

    existing_master = allocation_repo.get_for_date(db, normalized.selected_date)
    if not existing_master:
        db.rollback()
        raise ConflictError(
            "This date has not been saved yet, so there is nothing to revise. Use Save Current Data instead.",
            code="DATE_NOT_SAVED",
        )

    try:
        before_allocation = audit_service.snapshot_allocations(
            [_stored_allocation_to_line(r) for r in existing_master.values()]
        )
        existing_flow = flow_repo.get_for_date(db, normalized.selected_date)
        before_flow = audit_service.snapshot_flow(
            [_stored_flow_to_line(r) for r in existing_flow.values()]
        )

        revision_number = audit_service.get_latest_revision_number(db, normalized.selected_date) + 1

        # A real transaction makes the legacy "delete then re-insert, and if
        # the re-insert fails restore the deleted rows" compensating-rollback
        # dance unnecessary: any failure below rolls the delete AND the
        # insert back together.
        allocation_repo.delete_for_date(db, normalized.selected_date)
        flow_repo.delete_for_date(db, normalized.selected_date)

        sector_by_key = {s.sector_key: s for s in allocation_sectors}
        flow_by_key = {s.sector_key: s for s in flow_sectors}
        allocation_repo.insert_rows(db, [
            AllocationRecord(
                allocation_date=normalized.selected_date, sector_id=sector_by_key[a.sector_key].id,
                priority=a.priority, purity=a.purity, previous_requirement=a.previous_requirement,
                today_required=a.today_required, alloted=a.alloted, balance=a.balance,
            )
            for a in normalized.allocations
        ])
        flow_repo.insert_rows(db, [
            FlowRecord(flow_date=normalized.selected_date, flow_sector_id=flow_by_key[f.sector_key].id, acquired=f.today_acquired)
            for f in normalized.metal_flow
        ])

        audit_id = audit_service.write_audit_entry(
            db,
            audit_service.AuditEntryInput(
                allocation_date=normalized.selected_date, action_type=audit_service.AuditAction.REVISE,
                revision_number=revision_number, user_email=user.email, reason=reason,
                previous_allocation=before_allocation, updated_allocation=audit_service.snapshot_allocations(normalized.allocations),
                previous_flow=before_flow, updated_flow=audit_service.snapshot_flow(normalized.metal_flow),
                status=audit_service.AuditStatus.SUCCESS, request_id=request_id,
            ),
        )

        db.commit()
        return ReviseResultOut(
            selected_date=normalized.selected_date, revision_number=revision_number, audit_id=audit_id,
            totals=_totals_to_schema(normalized.totals), request_id=request_id,
        )
    except Exception as exc:
        db.rollback()
        try:
            audit_service.write_audit_entry(
                db,
                audit_service.AuditEntryInput(
                    allocation_date=payload.selected_date, action_type=audit_service.AuditAction.FAILED_REVISION,
                    revision_number=0, user_email=user.email, reason=str(getattr(exc, "message", exc)),
                    status=audit_service.AuditStatus.FAILED, request_id=request_id,
                ),
            )
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        raise
