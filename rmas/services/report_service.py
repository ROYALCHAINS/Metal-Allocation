"""
services/report_service.py
Royal Metal Allocation System — Python port of ReportService.gs

Read-only history and dashboard aggregation. Every query is scope-filtered in
SQL before any client filter is applied (CLAUDE.md section 6, rule 8).

SCOPE OF THIS PORT. History queries, the byDate/bySector/byPriority series, the
six dashboard KPI cards, topPending and the flow heatmap are all ported. The
heatmap lives in routers/reports.py's flow_analysis endpoint.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from repository import report_repo
from services.scope_service import UserScope
from services.validation_service import normalize_key

# From legacy's REPORT_CONFIG.
MAX_TREND_POINTS = 120
TOP_SECTOR_LIMIT = 10


@dataclass
class CycleDelta:
    """The newer half of a range against the older half."""

    previous_g: int = 0
    current_g: int = 0
    day_count: int = 0
    change_percent: float | None = None


def cycle_delta(day_totals: dict[str, int]) -> CycleDelta:
    """Split the saved dates down the middle; newer half vs older half.

    Ports renderCycleDelta(), shared by the Analysis Dashboard and Metal Flow
    History because both cards ask the same question. With an odd number of
    dates the extra date joins the CURRENT half, which never inflates the
    change. Returns a null change below four dates, or when the older half is
    zero — a change from zero is undefined, not infinite.

    Note this compares the two halves of the SELECTED range against each other,
    not the range against the calendar window before it. A range with no
    earlier data therefore still gets a comparison.
    """
    dates = sorted(day_totals)
    half = len(dates) // 2
    previous = sum(day_totals[d] for d in dates[:half])
    current = sum(day_totals[d] for d in dates[half:])

    change = None
    if len(dates) >= 4 and previous > 0:
        change = round((current - previous) / previous * 100, 1)

    return CycleDelta(
        previous_g=previous,
        current_g=current,
        day_count=len(dates) - half,
        change_percent=change,
    )


@dataclass
class DateSeriesPoint:
    allocation_date: str
    previous_requirement_g: int
    today_required_g: int
    alloted_g: int
    balance_g: int
    acquired_g: int


@dataclass
class SectorSeriesPoint:
    sector_name: str
    priority: str
    today_required_g: int
    alloted_g: int
    balance_g: int


@dataclass
class PrioritySeriesPoint:
    priority: str
    today_required_g: int
    alloted_g: int
    balance_g: int


@dataclass
class TopPendingPoint:
    sector_name: str
    priority: str
    pending_g: int
    as_of: str


@dataclass
class DashboardSummary:
    # --- the six KPI cards -------------------------------------------------
    saved_days: int = 0
    latest_saved_date: str | None = None
    utilisation_rate: float | None = None
    average_daily_acquired_g: int = 0
    by_date: list[DateSeriesPoint] = field(default_factory=list)
    by_sector: list[SectorSeriesPoint] = field(default_factory=list)
    by_priority: list[PrioritySeriesPoint] = field(default_factory=list)
    top_pending: list[TopPendingPoint] = field(default_factory=list)
    cycle: CycleDelta = field(default_factory=CycleDelta)
    # True when a sector filter was asked for but NOT applied to the supply
    # side, because that sector name does not exist in the flow ledger.
    flow_filter_skipped: bool = False
    total_acquired_g: int = 0
    total_alloted_g: int = 0
    total_required_g: int = 0
    closing_balance_g: int = 0
    saved_date_count: int = 0
    peak_closing_balance_g: int = 0
    peak_closing_date: str | None = None
    # alloted / acquired, as a percentage, 1 decimal. None when nothing acquired.
    fulfilment_rate: float | None = None


def _resolve_flow_sector(
    db: Session,
    scope: UserScope,
    *,
    sector_name: str | None,
    date_from: str | None,
    date_to: str | None,
) -> int | None:
    """Match an ALLOCATION sector name to a flow sector that has records.

    The cross-ledger rule (page spec, rule 2): the two ledgers keep separate
    sector tables, so an allocation-sector filter must not be pushed blindly at
    the flow ledger — doing so would blank the acquired series and make the
    dashboard look like no metal arrived. Filter supply only when the selected
    name genuinely exists on the supply side.

    Matched on the normalised NAME, not the id: the ids are from different
    tables and mean different things.
    """
    if not sector_name:
        return None
    wanted = normalize_key(sector_name)
    for flow_sector_id, name in report_repo.present_flow_sectors(
        db, scope, date_from=date_from, date_to=date_to
    ):
        if normalize_key(name) == wanted:
            return flow_sector_id
    return None


def get_dashboard_summary(
    db: Session,
    scope: UserScope,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    sector_id: int | None = None,
    sector_name: str | None = None,
) -> DashboardSummary:
    flow_sector_id = _resolve_flow_sector(
        db, scope, sector_name=sector_name, date_from=date_from, date_to=date_to
    )

    by_date_rows = report_repo.totals_by_date(
        db, scope, date_from=date_from, date_to=date_to, sector_id=sector_id
    )
    acquired_rows = dict(
        report_repo.acquired_by_date(
            db, scope, date_from=date_from, date_to=date_to, flow_sector_id=flow_sector_id
        )
    )

    by_date = [
        DateSeriesPoint(
            allocation_date=row[0],
            previous_requirement_g=row[1] or 0,
            today_required_g=row[2] or 0,
            alloted_g=row[3] or 0,
            balance_g=row[4] or 0,
            acquired_g=acquired_rows.get(row[0], 0) or 0,
        )
        for row in by_date_rows
    ]
    # Most recent points only — a long range would otherwise draw a bar chart
    # with more bars than the card has pixels.
    by_date = by_date[-MAX_TREND_POINTS:]

    shared = {"date_from": date_from, "date_to": date_to, "sector_id": sector_id}

    by_sector = [
        SectorSeriesPoint(
            sector_name=row[0],
            priority=row[1],
            today_required_g=row[2] or 0,
            alloted_g=row[3] or 0,
            balance_g=row[4] or 0,
        )
        for row in report_repo.totals_by_sector(db, scope, **shared)
    ]

    by_priority = [
        PrioritySeriesPoint(
            priority=row[0],
            today_required_g=row[1] or 0,
            alloted_g=row[2] or 0,
            balance_g=row[3] or 0,
        )
        for row in report_repo.totals_by_priority(db, scope, **shared)
    ]

    # Each sector's own latest saved date, kept only while still outstanding.
    top_pending = sorted(
        (
            TopPendingPoint(
                sector_name=row[0], priority=row[1], as_of=row[2], pending_g=row[3] or 0
            )
            for row in report_repo.latest_balance_by_sector(db, scope, **shared)
            if (row[3] or 0) > 0
        ),
        key=lambda p: p.pending_g,
        reverse=True,
    )[:TOP_SECTOR_LIMIT]

    total_acquired = sum(p.acquired_g for p in by_date)
    total_alloted = sum(p.alloted_g for p in by_date)

    peak = max(by_date, key=lambda p: p.balance_g, default=None)
    total_required = sum(p.today_required_g for p in by_date)

    cycle = cycle_delta({p.allocation_date: p.acquired_g for p in by_date})
    saved_days = len(by_date)

    return DashboardSummary(
        saved_days=saved_days,
        latest_saved_date=by_date[-1].allocation_date if by_date else None,
        top_pending=top_pending,
        cycle=cycle,
        flow_filter_skipped=bool(sector_name) and flow_sector_id is None,
        # Alloted against acquired — can exceed 100%, since over-allocation is
        # permitted (BLOCK_OVER_ALLOCATION is off).
        utilisation_rate=(
            round(total_alloted / total_acquired * 100, 1) if total_acquired else None
        ),
        average_daily_acquired_g=total_acquired // saved_days if saved_days else 0,
        by_date=by_date,
        by_sector=by_sector,
        by_priority=by_priority,
        total_acquired_g=total_acquired,
        total_alloted_g=total_alloted,
        total_required_g=total_required,
        # The latest saved date's closing balance, not a sum across dates —
        # balances carry forward, so summing them would double-count.
        closing_balance_g=by_date[-1].balance_g if by_date else 0,
        saved_date_count=len(by_date),
        peak_closing_balance_g=peak.balance_g if peak else 0,
        peak_closing_date=peak.allocation_date if peak else None,
        # NOTE: the dashboard's fulfilment rate is alloted / today_required.
        # Allocation History uses alloted / (previous_requirement + today_required)
        # instead — two different definitions, each matching its own screenshot.
        # Raised rather than silently unified; see the session log.
        fulfilment_rate=(
            round(total_alloted / total_required * 100, 1) if total_required > 0 else None
        ),
    )
