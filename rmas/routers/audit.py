"""
routers/audit.py
Royal Metal Allocation System — Python port of AuditReportService.gs

Administrator-only, read-only. Writes nothing, and there is deliberately no
update or delete route at any layer (rule 3).

`require_admin` re-checks admin status on the SERVER for every one of these
endpoints — hiding the tab in the browser is convenience, never protection
(legacy's assertAuditAccess_(), and CLAUDE.md rule 8). The deny list overrides
an admin grant here as everywhere else, and any failure to resolve identity
fails closed.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models.audit import MetalAllocationAuditLog
from models.user import AppUser
from repository import audit_repo
from routers.deps import require_admin
from schemas.audit import (
    AuditCounts,
    AuditChildRef,
    AuditEntryDetail,
    AuditEntryRow,
    AuditFilterOptions,
    AuditLogResponse,
    AuditLogSummary,
    DiffRow,
    DiffSide,
    DiffTotals,
)
from services.audit_report_service import (
    DEFAULT_RANGE_DAYS,
    MAX_ROWS_RETURNED,
    decode_allocation_snapshot,
    decode_flow_snapshot,
    diff_allocation_snapshots,
    diff_flow_snapshots,
    format_audit_timestamp,
    preview_reason,
)
from services.audit_report_service import allocation_totals as _allocation_totals
from services.audit_report_service import flow_totals as _flow_totals
from services.date_service import format_display_date
from services.weight_service import grams_to_kg

router = APIRouter(prefix="/audit", tags=["audit"])


def _display_date(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return format_display_date(date.fromisoformat(iso))
    except ValueError:
        return None


def _has_snapshots(entry: MetalAllocationAuditLog) -> bool:
    """False for blocked and failed entries, where nothing was captured — the
    page disables the View changes button rather than opening an empty modal."""
    return any(
        (
            entry.previous_allocation_data,
            entry.updated_allocation_data,
            entry.previous_metal_flow_data,
            entry.updated_metal_flow_data,
        )
    )


@router.get("/filter-options", response_model=AuditFilterOptions)
def filter_options(
    _admin: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AuditFilterOptions:
    """Fetched once by the page to build the three selects and seed the dates."""
    actions, statuses, users = audit_repo.distinct_filter_values(db)
    min_date, max_date, _dated_count = audit_repo.date_bounds(db)

    # The suggested window counts back from the latest AUDITED date, not from
    # today: an audit log that has been quiet for a month should still open
    # showing entries rather than an empty table.
    latest = max_date or date.today().isoformat()
    suggested_from = (
        date.fromisoformat(latest) - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    ).isoformat()
    if min_date and suggested_from < min_date:
        suggested_from = min_date

    return AuditFilterOptions(
        actions=actions,
        statuses=statuses,
        users=users,
        entry_count=audit_repo.total_entry_count(db),
        min_date=min_date or None,
        max_date=max_date or None,
        suggested_from=suggested_from,
        suggested_to=latest,
    )


@router.get("", response_model=AuditLogResponse)
def get_audit_log(
    date_from: date | None = None,
    date_to: date | None = None,
    action_type: str | None = None,
    status: str | None = None,
    user: str | None = None,
    search: str | None = None,
    limit: int = Query(MAX_ROWS_RETURNED, ge=1, le=MAX_ROWS_RETURNED),
    _admin: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AuditLogResponse:
    """Truncation, not pagination — this page has no pager (rule 10)."""
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    filters = {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "action_type": action_type,
        "status": status,
        "user": user,
        "search": search,
    }

    # Counted over the full matched set, before the limit is applied.
    counts = audit_repo.count_by_status(db, **filters)
    entries = audit_repo.query_log(db, limit=limit, **filters)

    return AuditLogResponse(
        rows=[
            AuditEntryRow(
                audit_id=e.audit_id,
                allocation_date=e.allocation_date or None,
                allocation_date_display=_display_date(e.allocation_date),
                action_type=e.action_type,
                action_status=e.action_status,
                revision_number=e.revision_number,
                user_email=e.user_email,
                timestamp_display=format_audit_timestamp(e.action_timestamp),
                reason_preview=preview_reason(e.revision_reason),
                request_id=e.request_id,
                has_snapshots=_has_snapshots(e),
            )
            for e in entries
        ],
        summary=AuditLogSummary(
            record_count=counts["total"],
            returned_count=len(entries),
            truncated=counts["total"] > len(entries),
            counts=AuditCounts(**counts),
        ),
    )


_ALLOCATION_KG = {
    "previous_requirement": "previous_requirement_kg",
    "today_required": "today_required_kg",
    "alloted": "alloted_kg",
    "balance": "balance_kg",
}


def _side(row, *, flow: bool) -> DiffSide | None:
    """One side of a comparison, or None when the sector is absent there."""
    if row is None:
        return None
    if flow:
        return DiffSide(
            sector_name=row.sector_name,
            acquired_kg=grams_to_kg(row.values_g.get("acquired", 0)),
        )
    return DiffSide(
        sector_name=row.sector_name,
        priority=row.priority,
        purity=row.purity,
        **{
            kg_field: grams_to_kg(row.values_g.get(name, 0))
            for name, kg_field in _ALLOCATION_KG.items()
        },
    )


def _rows(diff, *, flow: bool) -> list[DiffRow]:
    return [
        DiffRow(
            sector_name=d.sector_name,
            before=_side(d.before, flow=flow),
            after=_side(d.after, flow=flow),
            changed=d.changed,
            any_change=d.any_change,
            only_before=d.only_before,
            only_after=d.only_after,
        )
        for d in diff
    ]


def _totals(raw: dict[str, int], *, flow: bool) -> DiffTotals:
    if flow:
        return DiffTotals(
            row_count=raw["row_count"], acquired_kg=grams_to_kg(raw["acquired"])
        )
    return DiffTotals(
        row_count=raw["row_count"],
        **{
            kg_field: grams_to_kg(raw[name]) for name, kg_field in _ALLOCATION_KG.items()
        },
    )


@router.get("/entry/{audit_id}", response_model=AuditEntryDetail)
def get_audit_entry(
    audit_id: str,
    _admin: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AuditEntryDetail:
    """One entry with its before/after comparison built server-side.

    The route is /entry/{id} rather than /{id} so it cannot swallow
    /filter-options.
    """
    if not audit_id.strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_AUDIT_ID", "message": "No audit entry was specified."},
        )

    entry = audit_repo.get_entry(db, audit_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "AUDIT_ENTRY_NOT_FOUND",
                "message": "That audit entry no longer exists in the log.",
            },
        )

    before_alloc = decode_allocation_snapshot(entry.previous_allocation_data)
    after_alloc = decode_allocation_snapshot(entry.updated_allocation_data)
    before_flow = decode_flow_snapshot(entry.previous_metal_flow_data)
    after_flow = decode_flow_snapshot(entry.updated_metal_flow_data)

    allocation_diff = diff_allocation_snapshots(before_alloc, after_alloc)
    flow_diff = diff_flow_snapshots(before_flow, after_flow)

    return AuditEntryDetail(
        audit_id=entry.audit_id,
        allocation_date=entry.allocation_date or None,
        allocation_date_display=_display_date(entry.allocation_date),
        action_type=entry.action_type,
        action_status=entry.action_status,
        revision_number=entry.revision_number,
        user_email=entry.user_email,
        timestamp_display=format_audit_timestamp(entry.action_timestamp),
        reason=entry.revision_reason,
        request_id=entry.request_id,
        has_before=bool(before_alloc or before_flow),
        has_after=bool(after_alloc or after_flow),
        allocation_diff=_rows(allocation_diff, flow=False),
        flow_diff=_rows(flow_diff, flow=True),
        before_allocation_totals=_totals(_allocation_totals(before_alloc), flow=False),
        after_allocation_totals=_totals(_allocation_totals(after_alloc), flow=False),
        before_flow_totals=_totals(_flow_totals(before_flow), flow=True),
        after_flow_totals=_totals(_flow_totals(after_flow), flow=True),
        parent_audit_id=entry.parent_audit_id,
        children=[
            AuditChildRef(
                audit_id=child.audit_id,
                allocation_date=child.allocation_date,
                allocation_date_display=_display_date(child.allocation_date),
            )
            for child in audit_repo.get_children(db, entry.audit_id)
        ],
        changed_sectors=sum(1 for d in allocation_diff if d.any_change),
        changed_flow_sectors=sum(1 for d in flow_diff if d.any_change),
    )
