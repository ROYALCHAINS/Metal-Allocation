"""
routers/reports.py
Royal Metal Allocation System — Python port

Allocation History, Metal Flow History and the Analysis Dashboard. Read-only.

The caller never says which party they want — scope is resolved server-side from
the session and applied in SQL before any filter supplied here (rule 8).
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from models.audit import MetalAllocationAuditLog
from models.sector import FlowSector, Sector
from models.user import AppUser
from repository import report_repo
from repository.sector_repo import get_all_party_ids
from repository.user_repo import get_flow_sector_ids_for_user, get_party_ids_for_user
from routers.deps import get_current_user
from schemas.report import (
    AllocationHistoryResponse,
    AllocationHistoryRow,
    AllocationHistorySummary,
    PageInfo,
    PeakBalance,
    DashboardResponse,
    DatePoint,
    FlowHistoryResponse,
    FlowHistoryRow,
    FlowAnalysisResponse,
    CycleDelta,
    FlowHeatmap,
    FlowMostActive,
    FlowPeak,
    FlowSummary,
    HeatmapCell,
    HeatmapDate,
    HeatmapSector,
    NavCounts,
    PriorityPoint,
    SectorPoint,
    TopPendingPoint,
)
from services.date_service import format_display_date
from services.report_service import cycle_delta, get_dashboard_summary
from services.scope_service import build_scope, is_administrator
from services.weight_service import grams_to_kg

router = APIRouter(prefix="/reports", tags=["reports"])


def _scope(db: Session, user: AppUser):
    return build_scope(
        user,
        party_ids=get_party_ids_for_user(db, user.user_id),
        flow_sector_ids=get_flow_sector_ids_for_user(db, user.user_id),
        all_party_ids=get_all_party_ids(db),
    )


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


# Limits from legacy's REPORT_CONFIG.
PAGE_SIZE = 100
MAX_ROWS_RETURNED = 3000
DEFAULT_RANGE_DAYS = 30


@router.get("/allocation-history", response_model=AllocationHistoryResponse)
def allocation_history(
    date_from: date | None = None,
    date_to: date | None = None,
    party_id: int | None = None,
    sector_id: int | None = None,
    status: str = "all",
    limit: int = PAGE_SIZE,
    offset: int = 0,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AllocationHistoryResponse:
    """Allocation History.

    Per the page spec: a reversed date range is SWAPPED rather than rejected,
    a limit outside 1..3000 falls back to the page size, and a negative offset
    becomes 0 — invalid input is corrected, not refused.
    """
    scope = _scope(db, user)
    if not scope.unrestricted and not scope.party_ids:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "NO_PARTY_ASSIGNED",
                "message": "No party is assigned to your account. Contact the administrator.",
            },
        )

    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    if date_from is None and date_to is None:
        date_to = date.today()
        date_from = date_to - timedelta(days=DEFAULT_RANGE_DAYS)

    if not 1 <= limit <= MAX_ROWS_RETURNED:
        limit = PAGE_SIZE
    offset = max(0, offset)

    filters = {
        "date_from": _iso(date_from),
        "date_to": _iso(date_to),
        "party_id": party_id,
        "sector_id": sector_id,
        "status": status,
    }

    rows = report_repo.allocation_history(db, scope, limit=limit, offset=offset, **filters)
    (
        record_count,
        date_count,
        sector_count,
        total_prev_g,
        total_req_g,
        total_alloted_g,
        total_balance_g,
    ) = report_repo.allocation_history_summary(db, scope, **filters)
    peak = report_repo.allocation_peak_balance(db, scope, **filters)

    # demand = previous_requirement + today_required; fulfilment = alloted/demand.
    # Demand <= 0 reports 0, never a large number — a negative previous
    # requirement means the sector is carrying credit from earlier
    # over-allocation.
    total_demand_g = total_prev_g + total_req_g
    fulfilment = round(total_alloted_g / total_demand_g * 100, 1) if total_demand_g > 0 else 0.0

    total_pages = max(1, -(-record_count // limit))  # ceiling division
    current_page = offset // limit + 1

    return AllocationHistoryResponse(
        rows=[
            AllocationHistoryRow(
                allocation_date=date.fromisoformat(master.allocation_date),
                date_display=format_display_date(date.fromisoformat(master.allocation_date)),
                sector_name=sector.sector_name,
                party_name=party.party_name,
                priority=master.priority_snapshot,
                purity=master.purity_snapshot,
                previous_requirement_kg=grams_to_kg(master.previous_requirement_g),
                today_required_kg=grams_to_kg(master.today_required_g),
                alloted_kg=grams_to_kg(master.alloted_g),
                balance_kg=grams_to_kg(master.balance_g),
                revision_number=master.revision_number,
            )
            for master, sector, party in rows
        ],
        total_rows=record_count,
        summary=AllocationHistorySummary(
            record_count=record_count,
            returned_count=len(rows),
            truncated=record_count > MAX_ROWS_RETURNED,
            date_count=date_count,
            sector_count=sector_count,
            total_previous_requirement_kg=grams_to_kg(total_prev_g),
            total_today_required_kg=grams_to_kg(total_req_g),
            total_alloted_kg=grams_to_kg(total_alloted_g),
            total_balance_kg=grams_to_kg(total_balance_g),
            total_demand_kg=grams_to_kg(total_demand_g),
            fulfilment_rate=fulfilment,
            peak_balance=PeakBalance(
                value_kg=grams_to_kg(peak[1] if peak else 0),
                date_display=(
                    format_display_date(date.fromisoformat(peak[0])) if peak else None
                ),
            ),
        ),
        page=PageInfo(
            current_page=current_page,
            total_pages=total_pages,
            page_size=limit,
            offset=offset,
            total_records=record_count,
            first_record=offset + 1 if record_count else 0,
            last_record=min(offset + len(rows), record_count),
            has_previous=offset > 0,
            has_next=offset + len(rows) < record_count,
        ),
    )


@router.get("/flow-history", response_model=FlowHistoryResponse)
def flow_history(
    date_from: date | None = None,
    date_to: date | None = None,
    party_id: int | None = None,
    limit: int = Query(500, le=500),
    offset: int = 0,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FlowHistoryResponse:
    scope = _scope(db, user)
    filters = {"date_from": _iso(date_from), "date_to": _iso(date_to), "party_id": party_id}
    rows = report_repo.flow_history(db, scope, limit=limit, offset=offset, **filters)
    return FlowHistoryResponse(
        rows=[
            FlowHistoryRow(
                allocation_date=date.fromisoformat(flow.allocation_date),
                sector_name=sector.sector_name,
                party_name=party.party_name,
                acquired_kg=grams_to_kg(flow.acquired_g),
                revision_number=flow.revision_number,
            )
            for flow, sector, party in rows
        ],
        total_rows=report_repo.flow_history_count(db, scope, **filters),
    )


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    date_from: date | None = None,
    date_to: date | None = None,
    sector_id: int | None = None,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    """The only page that joins both ledgers — demand and supply together.

    Both are scope-filtered independently in SQL before any client filter
    (page spec, rule 1).
    """
    scope = _scope(db, user)
    if not scope.unrestricted and not scope.party_ids:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "NO_PARTY_ASSIGNED",
                "message": "No party is assigned to your account. Contact the administrator.",
            },
        )

    # The name, not the id, is what the flow ledger can be matched on.
    sector_name = db.scalar(select(Sector.sector_name).where(Sector.sector_id == sector_id))
    summary = get_dashboard_summary(
        db,
        scope,
        date_from=_iso(date_from),
        date_to=_iso(date_to),
        sector_id=sector_id,
        sector_name=sector_name,
    )
    return DashboardResponse(
        saved_days=summary.saved_days,
        latest_saved_date=(
            date.fromisoformat(summary.latest_saved_date) if summary.latest_saved_date else None
        ),
        latest_saved_date_display=(
            format_display_date(date.fromisoformat(summary.latest_saved_date))
            if summary.latest_saved_date
            else None
        ),
        utilisation_rate=summary.utilisation_rate,
        average_daily_acquired_kg=grams_to_kg(summary.average_daily_acquired_g),
        by_date=[
            DatePoint(
                allocation_date=date.fromisoformat(p.allocation_date),
                previous_requirement_kg=grams_to_kg(p.previous_requirement_g),
                today_required_kg=grams_to_kg(p.today_required_g),
                alloted_kg=grams_to_kg(p.alloted_g),
                balance_kg=grams_to_kg(p.balance_g),
                acquired_kg=grams_to_kg(p.acquired_g),
            )
            for p in summary.by_date
        ],
        by_sector=[
            SectorPoint(
                sector_name=p.sector_name,
                priority=p.priority,
                today_required_kg=grams_to_kg(p.today_required_g),
                alloted_kg=grams_to_kg(p.alloted_g),
                balance_kg=grams_to_kg(p.balance_g),
            )
            for p in summary.by_sector
        ],
        by_priority=[
            PriorityPoint(
                priority=p.priority,
                today_required_kg=grams_to_kg(p.today_required_g),
                alloted_kg=grams_to_kg(p.alloted_g),
                balance_kg=grams_to_kg(p.balance_g),
            )
            for p in summary.by_priority
        ],
        total_acquired_kg=grams_to_kg(summary.total_acquired_g),
        total_alloted_kg=grams_to_kg(summary.total_alloted_g),
        total_required_kg=grams_to_kg(summary.total_required_g),
        closing_balance_kg=grams_to_kg(summary.closing_balance_g),
        saved_date_count=summary.saved_date_count,
        peak_closing_balance_kg=grams_to_kg(summary.peak_closing_balance_g),
        peak_closing_date=(
            date.fromisoformat(summary.peak_closing_date) if summary.peak_closing_date else None
        ),
        peak_closing_date_display=(
            format_display_date(date.fromisoformat(summary.peak_closing_date))
            if summary.peak_closing_date
            else None
        ),
        fulfilment_rate=summary.fulfilment_rate,
        cycle=CycleDelta(
            previous_acquired_kg=grams_to_kg(summary.cycle.previous_g),
            current_acquired_kg=grams_to_kg(summary.cycle.current_g),
            day_count=summary.cycle.day_count,
            change_percent=summary.cycle.change_percent,
        ),
        top_pending=[
            TopPendingPoint(
                sector_name=p.sector_name,
                priority=p.priority,
                pending_kg=grams_to_kg(p.pending_g),
                as_of=date.fromisoformat(p.as_of),
                as_of_display=format_display_date(date.fromisoformat(p.as_of)),
            )
            for p in summary.top_pending
        ],
        is_admin=is_administrator(user),
        flow_filter_skipped=summary.flow_filter_skipped,
    )


# From legacy's REPORT_CONFIG / ReportService.gs.
MAX_HEATMAP_DATES = 180
HEATMAP_WINDOW_DAYS = 30


def _cycle_schema(day_totals: dict[str, int]) -> CycleDelta:
    """The service owns the rule; this only puts it on the wire in kilograms."""
    cycle = cycle_delta(day_totals)
    return CycleDelta(
        previous_acquired_kg=grams_to_kg(cycle.previous_g),
        current_acquired_kg=grams_to_kg(cycle.current_g),
        day_count=cycle.day_count,
        change_percent=cycle.change_percent,
    )


@router.get("/flow-analysis", response_model=FlowAnalysisResponse)
def flow_analysis(
    date_from: date | None = None,
    date_to: date | None = None,
    sector_id: int | None = None,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FlowAnalysisResponse:
    """Metal Flow History — supply, as opposed to Allocation History's demand.

    Chart-only: no table and no pager, deliberately (page spec, rule 9).
    Everything drawn is built from EVERY matched record, never from a page.

    Ports buildFlowSeries_() / buildFlowHeatmap_() / limitFlowToWindow_():
    zero-total sectors are dropped from both charts, duplicate (date, sector)
    records are summed, and the heatmap window counts back from the NEWEST
    MATCHED DATE rather than from today.
    """
    scope = _scope(db, user)
    if not scope.unrestricted and not scope.party_ids:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "NO_PARTY_ASSIGNED",
                "message": "No party is assigned to your account. Contact the administrator.",
            },
        )

    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    if date_from is None and date_to is None:
        date_to = date.today()
        date_from = date_to - timedelta(days=DEFAULT_RANGE_DAYS)

    filters = {"date_from": _iso(date_from), "date_to": _iso(date_to), "sector_id": sector_id}
    # flow_summary's sector count is "sectors with a record"; the card wants
    # "sectors that actually acquired something", so it is recomputed below.
    record_count, date_count, _sectors_with_a_record, total_acquired_g = report_repo.flow_summary(
        db, scope, **filters
    )
    cells = report_repo.flow_cells(db, scope, **filters)

    # Sector totals over the WHOLE range (the share chart's basis) and day
    # totals for the cycle delta. flow_cells() already sums duplicates.
    sector_totals: dict[int, int] = {}
    sector_names: dict[int, str] = {}
    day_totals: dict[str, int] = {}
    for iso_date, flow_sector_id, sector_name, acquired_g in cells:
        sector_totals[flow_sector_id] = sector_totals.get(flow_sector_id, 0) + acquired_g
        sector_names[flow_sector_id] = sector_name
        day_totals[iso_date] = day_totals.get(iso_date, 0) + acquired_g

    # Heatmap window: 30 days back from the newest MATCHED date, not today.
    all_dates = sorted(day_totals)
    window_cells = cells
    if all_dates:
        newest = date.fromisoformat(all_dates[-1])
        window_start = (newest - timedelta(days=HEATMAP_WINDOW_DAYS - 1)).isoformat()
        window_cells = [c for c in cells if c[0] >= window_start]

    window_dates = sorted({c[0] for c in window_cells})
    truncated = len(window_dates) > MAX_HEATMAP_DATES
    kept_dates = window_dates[-MAX_HEATMAP_DATES:] if truncated else window_dates
    kept_date_set = set(kept_dates)

    # Zero-total sectors are excluded from both charts (rule 5).
    kept = {sid: total for sid, total in sector_totals.items() if total > 0}
    ordered = sorted(kept.items(), key=lambda kv: (-kv[1], sector_names[kv[0]]))

    grid = [c for c in window_cells if c[0] in kept_date_set and c[1] in kept]

    # Highest single CELL, not the highest day total.
    peak_cell = max(grid, key=lambda c: c[3], default=None)
    busiest = max(day_totals.items(), key=lambda kv: kv[1], default=None)
    top = ordered[0] if ordered else None

    return FlowAnalysisResponse(
        summary=FlowSummary(
            record_count=record_count,
            date_count=date_count,
            sector_count=len(kept),
            total_sector_count=db.scalar(select(func.count()).select_from(FlowSector)) or 0,
            total_acquired_kg=grams_to_kg(total_acquired_g),
            # Divided by dates WITH records, not calendar days. 0 when none.
            average_per_day_kg=grams_to_kg(
                total_acquired_g // date_count if date_count else 0
            ),
            cycle=_cycle_schema(day_totals),
        ),
        heatmap=FlowHeatmap(
            dates=[
                HeatmapDate(
                    date_key=date.fromisoformat(d),
                    short_label=d[5:],
                    full_label=format_display_date(date.fromisoformat(d)),
                )
                for d in kept_dates
            ],
            sectors=[
                HeatmapSector(
                    flow_sector_id=sid,
                    sector_name=sector_names[sid],
                    total_kg=grams_to_kg(total),
                )
                for sid, total in ordered
            ],
            cells=[
                HeatmapCell(
                    date_key=date.fromisoformat(iso),
                    flow_sector_id=sid,
                    acquired_kg=grams_to_kg(g),
                )
                for iso, sid, _name, g in grid
            ],
            max_acquired_kg=grams_to_kg(max((c[3] for c in grid), default=0)),
            truncated=truncated,
            truncation_note=(
                f"Showing the most recent {len(kept_dates)} days. "
                "Narrow the range to see earlier dates."
                if truncated
                else None
            ),
            window_days=HEATMAP_WINDOW_DAYS,
            peak=FlowPeak(
                acquired_kg=grams_to_kg(peak_cell[3] if peak_cell else 0),
                sector_name=sector_names.get(peak_cell[1]) if peak_cell else None,
                full_date_label=(
                    format_display_date(date.fromisoformat(peak_cell[0]))
                    if peak_cell
                    else None
                ),
            ),
            most_active=FlowMostActive(
                sector_name=sector_names[top[0]] if top else None,
                total_kg=grams_to_kg(top[1] if top else 0),
                percent=(
                    round(top[1] / total_acquired_g * 100, 1)
                    if top and total_acquired_g
                    else 0.0
                ),
            ),
            busiest_day_kg=grams_to_kg(busiest[1] if busiest else 0),
            busiest_day_label=(
                format_display_date(date.fromisoformat(busiest[0])) if busiest else None
            ),
        ),
    )


@router.get("/counts", response_model=NavCounts)
def nav_counts(
    user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> NavCounts:
    """Record counts for the nav tab pills. Scoped like everything else, so an
    operator's pills reflect only what they can actually see."""
    scope = _scope(db, user)
    audit_total = 0
    if is_administrator(user):
        audit_total = db.scalar(select(func.count()).select_from(MetalAllocationAuditLog)) or 0
    return NavCounts(
        allocation_history=report_repo.allocation_history_count(db, scope),
        flow_history=report_repo.flow_history_count(db, scope),
        audit=audit_total,
    )
