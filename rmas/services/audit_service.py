"""
audit_service.py
Royal Metal Allocation System — Python port

Ports AuditService.gs (the append-only writer) and AuditReportService.gs
(the admin-only read/diff side — the file CLAUDE.md's original mapping table
omitted; see the review that preceded this port). CLAUDE.md 6.13: the audit
log is append-only — no function in this module updates or deletes a row.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date as date_, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from rmas.models.audit import AuditLogEntry
from rmas.repository import audit_repo
from rmas.schemas.audit import (
    AllocationDiffRowOut,
    AllocationSnapshotRowOut,
    AuditCountsOut,
    AuditEntryDetailOut,
    AuditEntryTotalsOut,
    AuditFilterOptionsOut,
    AuditFilters,
    AuditLogOut,
    AuditLogRowOut,
    AuditLogSummaryOut,
    DateRevisionSummaryOut,
    FlowDiffRowOut,
    FlowSnapshotRowOut,
    SnapshotTotalsOut,
)
from rmas.services.date_service import app_timezone, format_display_date
from rmas.services.exceptions import ScopeError
from rmas.services.validation_service import nearly_equal, round3

logger = logging.getLogger(__name__)

AUDIT_REASON_PREVIEW_LIMIT = 140
AUDIT_DEFAULT_RANGE_DAYS = 90


class AuditAction:
    """Legacy AuditService.gs's AUDIT_ACTIONS plus StagingService.gs's
    stagingAuditAction_() values — both land in the same audit_log table."""

    SAVE = "SAVE"
    REVISE = "REVISE"
    BLOCKED_DUPLICATE = "BLOCKED_DUPLICATE"
    FAILED_SAVE = "FAILED_SAVE"
    FAILED_REVISION = "FAILED_REVISION"
    UNAUTHORIZED_REVISION = "UNAUTHORIZED_REVISION"
    SUBMIT_REQUIREMENT = "SUBMIT_REQUIREMENT"
    BLOCKED_RESUBMISSION = "BLOCKED_RESUBMISSION"
    FAILED_SUBMISSION = "FAILED_SUBMISSION"


class AuditStatus:
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


def generate_audit_id() -> str:
    """Legacy generateAuditId_() — e.g. AUD-20260818-104233-4821."""
    now = datetime.now(app_timezone())
    return f"AUD-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().int % 10000:04d}"


def generate_request_id() -> str:
    """Legacy generateRequestId_()."""
    return f"REQ-{uuid.uuid4()}"


def snapshot_allocations(allocations) -> list[dict]:
    """Legacy snapshotAllocations_(). Works on any object exposing the six fields."""
    return [
        {
            "p": a.priority, "s": a.sector, "pu": a.purity,
            "pr": str(round3(a.previous_requirement)),
            "tr": str(round3(a.today_required)),
            "al": str(round3(a.alloted)),
            "bl": str(round3(a.balance)),
        }
        for a in allocations
    ]


def snapshot_flow(flow_rows, acquired_attr: str = "today_acquired") -> list[dict]:
    """Legacy snapshotMetalFlow_() / snapshotStoredFlow_()."""
    return [{"s": f.sector, "ac": str(round3(getattr(f, acquired_attr)))} for f in flow_rows]


@dataclass
class AuditEntryInput:
    allocation_date: date_ | None
    action_type: str
    revision_number: int
    user_email: str
    reason: str
    status: str
    request_id: str = ""
    audit_id: str | None = None
    previous_allocation: list[dict] | None = None
    updated_allocation: list[dict] | None = None
    previous_flow: list[dict] | None = None
    updated_flow: list[dict] | None = None


def write_audit_entry(db: Session, entry: AuditEntryInput) -> str:
    """
    Legacy writeAuditEntry_(). Never raises: a logging failure must never
    mask or reverse a completed business operation. Callers wrap their own
    call to this in try/except for the same reason the legacy code does,
    even though this function already swallows its own errors.
    """
    audit_id = entry.audit_id or generate_audit_id()
    try:
        row = AuditLogEntry(
            audit_id=audit_id,
            allocation_date=entry.allocation_date,
            action_type=entry.action_type,
            revision_number=entry.revision_number,
            user_email=entry.user_email,
            action_timestamp=datetime.now(app_timezone()),
            reason=entry.reason,
            previous_allocation_data=entry.previous_allocation,
            updated_allocation_data=entry.updated_allocation,
            previous_flow_data=entry.previous_flow,
            updated_flow_data=entry.updated_flow,
            request_id=entry.request_id,
            action_status=entry.status,
        )
        return audit_repo.insert_entry(db, row)
    except Exception:  # noqa: BLE001 — audit writes must never block the caller
        logger.exception("AUDIT WRITE FAILED for %s / %s", entry.allocation_date, entry.action_type)
        return ""


def get_latest_revision_number(db: Session, allocation_date: date_) -> int:
    return audit_repo.latest_revision_number(db, allocation_date)


# ------------------------------------------------------------------------
# Read side — ported from AuditReportService.gs. Admin-only; callers (the
# router) must call assert_admin() from scope_service/auth before any of
# these, but each is re-checked here too, matching assertAuditAccess_()'s
# "hiding the tab is convenience, never protection" stance.
# ------------------------------------------------------------------------


def assert_audit_access(is_admin: bool) -> None:
    if not is_admin:
        raise ScopeError(
            "The audit log is restricted to authorized administrators.", code="NOT_AUTHORIZED"
        )


def _preview_reason(text: str) -> str:
    s = " ".join((text or "").split())
    if len(s) <= AUDIT_REASON_PREVIEW_LIMIT:
        return s
    return s[: AUDIT_REASON_PREVIEW_LIMIT - 1] + "…"


def get_filter_options(db: Session, is_admin: bool) -> AuditFilterOptionsOut:
    assert_audit_access(is_admin)
    rows = audit_repo.list_all(db)

    actions = sorted({r.action_type for r in rows if r.action_type})
    statuses = sorted({r.action_status for r in rows if r.action_status})
    users = sorted({r.user_email for r in rows if r.user_email})
    dates = sorted({r.allocation_date for r in rows if r.allocation_date})

    latest = dates[-1] if dates else None
    suggested_from = None
    if latest:
        from datetime import timedelta

        suggested_from = latest - timedelta(days=AUDIT_DEFAULT_RANGE_DAYS - 1)
        if dates and suggested_from < dates[0]:
            suggested_from = dates[0]

    return AuditFilterOptionsOut(
        actions=actions,
        statuses=statuses,
        users=users,
        entry_count=len(rows),
        min_date=dates[0] if dates else None,
        max_date=latest,
        suggested_from=suggested_from,
        suggested_to=latest,
    )


def get_audit_log(db: Session, is_admin: bool, filters: AuditFilters) -> AuditLogOut:
    assert_audit_access(is_admin)
    rows = audit_repo.list_all(db)

    def matches(r: AuditLogEntry) -> bool:
        if r.allocation_date:
            if filters.from_date and r.allocation_date < filters.from_date:
                return False
            if filters.to_date and r.allocation_date > filters.to_date:
                return False
        if filters.action_type != "all" and r.action_type != filters.action_type:
            return False
        if filters.status != "all" and r.action_status != filters.status:
            return False
        if filters.user != "all" and r.user_email.lower() != filters.user.lower():
            return False
        return True

    matched = [r for r in rows if matches(r)]
    matched.sort(key=lambda r: (r.action_timestamp, r.id), reverse=True)

    counts = AuditCountsOut(
        total=len(matched),
        success=sum(1 for r in matched if r.action_status == AuditStatus.SUCCESS),
        blocked=sum(1 for r in matched if r.action_status == AuditStatus.BLOCKED),
        failed=sum(1 for r in matched if r.action_status == AuditStatus.FAILED),
        revisions=sum(1 for r in matched if r.action_type == AuditAction.REVISE),
    )

    limit = filters.limit or 500
    truncated = len(matched) > limit
    page = matched[:limit]

    return AuditLogOut(
        rows=[
            AuditLogRowOut(
                audit_id=r.audit_id,
                allocation_date_key=r.allocation_date,
                allocation_date_display=format_display_date(r.allocation_date) if r.allocation_date else "—",
                action_type=r.action_type,
                revision_number=r.revision_number,
                user_email=r.user_email,
                timestamp_display=r.action_timestamp.strftime("%d-%b-%Y %H:%M:%S") if r.action_timestamp else "",
                reason_preview=_preview_reason(r.reason),
                request_id=r.request_id,
                status=r.action_status,
                has_snapshots=bool(
                    r.previous_allocation_data or r.updated_allocation_data
                    or r.previous_flow_data or r.updated_flow_data
                ),
            )
            for r in page
        ],
        summary=AuditLogSummaryOut(
            record_count=len(matched), returned_count=len(page), truncated=truncated, counts=counts
        ),
    )


def _decode_allocation_snapshot(raw: list[dict] | None) -> list[AllocationSnapshotRowOut]:
    if not raw:
        return []
    return [
        AllocationSnapshotRowOut(
            priority=str(r.get("p", "")), sector=str(r.get("s", "")), purity=str(r.get("pu", "")),
            previous_requirement=round3(Decimal(str(r.get("pr", 0)))),
            today_required=round3(Decimal(str(r.get("tr", 0)))),
            alloted=round3(Decimal(str(r.get("al", 0)))),
            balance=round3(Decimal(str(r.get("bl", 0)))),
        )
        for r in raw
    ]


def _decode_flow_snapshot(raw: list[dict] | None) -> list[FlowSnapshotRowOut]:
    if not raw:
        return []
    return [
        FlowSnapshotRowOut(sector=str(r.get("s", "")), acquired=round3(Decimal(str(r.get("ac", 0)))))
        for r in raw
    ]


def _allocation_snapshot_totals(rows: list[AllocationSnapshotRowOut]) -> SnapshotTotalsOut:
    t = SnapshotTotalsOut(count=len(rows))
    for r in rows:
        t.previous_requirement += r.previous_requirement
        t.today_required += r.today_required
        t.alloted += r.alloted
        t.balance += r.balance
    t.previous_requirement = round3(t.previous_requirement)
    t.today_required = round3(t.today_required)
    t.alloted = round3(t.alloted)
    t.balance = round3(t.balance)
    return t


def _flow_snapshot_totals(rows: list[FlowSnapshotRowOut]) -> SnapshotTotalsOut:
    total = sum((r.acquired for r in rows), Decimal("0"))
    return SnapshotTotalsOut(acquired=round3(total), count=len(rows))


def _diff_allocation_snapshots(
    before: list[AllocationSnapshotRowOut], after: list[AllocationSnapshotRowOut]
) -> list[AllocationDiffRowOut]:
    before_map = {r.sector: r for r in before}
    after_map = {r.sector: r for r in after}
    order: list[str] = []
    seen: set[str] = set()
    for r in before + after:
        if r.sector not in seen:
            seen.add(r.sector)
            order.append(r.sector)

    fields = ["previous_requirement", "today_required", "alloted", "balance"]
    out: list[AllocationDiffRowOut] = []
    for sector in order:
        b = before_map.get(sector)
        a = after_map.get(sector)
        changed = {}
        for f in fields:
            bv = getattr(b, f) if b else None
            av = getattr(a, f) if a else None
            changed[f] = True if (b is None or a is None) else not nearly_equal(bv, av)
        out.append(
            AllocationDiffRowOut(
                sector=sector,
                priority=(a or b).priority,
                before=b,
                after=a,
                changed=changed,
                any_change=any(changed.values()),
                only_before=bool(b and not a),
                only_after=bool(a and not b),
            )
        )
    return out


def _diff_flow_snapshots(
    before: list[FlowSnapshotRowOut], after: list[FlowSnapshotRowOut]
) -> list[FlowDiffRowOut]:
    before_map = {r.sector: r.acquired for r in before}
    after_map = {r.sector: r.acquired for r in after}
    order: list[str] = []
    seen: set[str] = set()
    for r in before + after:
        if r.sector not in seen:
            seen.add(r.sector)
            order.append(r.sector)

    out: list[FlowDiffRowOut] = []
    for sector in order:
        b = before_map.get(sector)
        a = after_map.get(sector)
        changed = True if (b is None or a is None) else not nearly_equal(b, a)
        out.append(
            FlowDiffRowOut(
                sector=sector, before=b, after=a, changed=changed,
                only_before=b is not None and a is None,
                only_after=a is not None and b is None,
            )
        )
    return out


def get_audit_entry_detail(db: Session, is_admin: bool, audit_id: str) -> AuditEntryDetailOut:
    assert_audit_access(is_admin)
    entry = audit_repo.get_by_audit_id(db, audit_id)
    if entry is None:
        from rmas.services.exceptions import NotFoundError

        raise NotFoundError("That audit entry no longer exists in the log.", code="AUDIT_ENTRY_NOT_FOUND")

    before_alloc = _decode_allocation_snapshot(entry.previous_allocation_data)
    after_alloc = _decode_allocation_snapshot(entry.updated_allocation_data)
    before_flow = _decode_flow_snapshot(entry.previous_flow_data)
    after_flow = _decode_flow_snapshot(entry.updated_flow_data)

    allocation_diff = _diff_allocation_snapshots(before_alloc, after_alloc)
    flow_diff = _diff_flow_snapshots(before_flow, after_flow)

    return AuditEntryDetailOut(
        audit_id=entry.audit_id,
        allocation_date_key=entry.allocation_date,
        allocation_date_display=format_display_date(entry.allocation_date) if entry.allocation_date else "—",
        action_type=entry.action_type,
        revision_number=entry.revision_number,
        user_email=entry.user_email,
        timestamp_display=entry.action_timestamp.strftime("%d-%b-%Y %H:%M:%S") if entry.action_timestamp else "",
        reason=entry.reason,
        request_id=entry.request_id,
        status=entry.action_status,
        has_before=bool(before_alloc or before_flow),
        has_after=bool(after_alloc or after_flow),
        allocation_diff=allocation_diff,
        flow_diff=flow_diff,
        totals=AuditEntryTotalsOut(
            before_allocation=_allocation_snapshot_totals(before_alloc),
            after_allocation=_allocation_snapshot_totals(after_alloc),
            before_flow=_flow_snapshot_totals(before_flow),
            after_flow=_flow_snapshot_totals(after_flow),
        ),
        changed_sectors=sum(1 for d in allocation_diff if d.any_change),
        changed_flow_sectors=sum(1 for d in flow_diff if d.changed),
    )


def get_date_revision_summary(db: Session, allocation_date: date_) -> DateRevisionSummaryOut:
    """
    Legacy getDateRevisionSummary(). Safe for every user (no admin gate) —
    returns counts and timestamps only, never snapshots.
    """
    rows = audit_repo.list_success_for_date(db, allocation_date)
    revisions = sorted(
        (r for r in rows if r.action_type == AuditAction.REVISE),
        key=lambda r: r.action_timestamp, reverse=True,
    )
    saves = sorted(
        (r for r in rows if r.action_type == AuditAction.SAVE),
        key=lambda r: r.action_timestamp,
    )
    latest = revisions[0] if revisions else None
    original = saves[0] if saves else None

    return DateRevisionSummaryOut(
        allocation_date=allocation_date,
        revision_count=len(revisions),
        latest_revision_number=latest.revision_number if latest else 0,
        last_revised_by=latest.user_email if latest else "",
        last_revised_at=latest.action_timestamp.strftime("%d-%b-%Y %H:%M:%S") if latest else "",
        last_revision_reason=latest.reason if latest else "",
        originally_saved_by=original.user_email if original else "",
        originally_saved_at=original.action_timestamp.strftime("%d-%b-%Y %H:%M:%S") if original else "",
    )
