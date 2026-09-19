"""
report_service.py
Royal Metal Allocation System — Python port

Ports ReportService.gs. STRICTLY READ ONLY — nothing here writes to any
table. Every query is scope-filtered server-side BEFORE any client-supplied
filter is applied (CLAUDE.md 6.8): an operator's filter selection can only
narrow, never widen, their own party's data.

The legacy "Search" and allocation-history "Purity" client-side controls
were removed from Reports.html (per its own comments), so this port does not
carry a `search` filter — it would have no caller. Priority/purity filters
remain supported server-side because ReportService.gs's dashboard filter
still applies `priorities`.
"""

from __future__ import annotations

import math
from datetime import date as date_, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from rmas.repository import allocation_repo, flow_repo, sector_repo
from rmas.schemas.common import PageInfo
from rmas.schemas.report import (
    AllocationHistoryOut,
    AllocationHistoryRowOut,
    AllocationHistorySummaryOut,
    CycleComparisonOut,
    DashboardByDateOut,
    DashboardByPriorityOut,
    DashboardBySectorOut,
    DashboardKpisOut,
    DashboardSummaryOut,
    FlowHistoryOut,
    FlowHistoryRowOut,
    FlowHistorySummaryOut,
    FlowSeriesOut,
    FlowSeriesSectorOut,
    HeatmapCellOut,
    HeatmapMostActiveOut,
    HeatmapOut,
    HeatmapPeakOut,
    HistoryFilterOptionsOut,
    HistoryFilters,
    LabelledOption,
    PeakBalanceOut,
    SectorOption,
    TopPendingOut,
)
from rmas.services.date_service import format_display_date, short_date_label
from rmas.services.exceptions import ScopeError
from rmas.services.scope_service import UserScope, scoped_allocation_sectors, scoped_flow_sectors
from rmas.services.validation_service import normalize_sector_key, round3

MAX_ROWS_RETURNED = 3000
PAGE_SIZE = 100
DEFAULT_RANGE_DAYS = 30
TOP_SECTOR_LIMIT = 10
MAX_TREND_POINTS = 120
MAX_HEATMAP_DATES = 180
HEATMAP_WINDOW_DAYS = 30


def _require_scope(scope: UserScope) -> frozenset[str] | None:
    if not scope.is_admin and not scope.parties:
        raise ScopeError(
            "No party is assigned to your account. Contact the administrator.", code="NO_PARTY_ASSIGNED"
        )
    return None if scope.unrestricted else scope.party_keys


def _normalize_filters(filters: HistoryFilters) -> HistoryFilters:
    """Legacy normalizeFilters_()."""
    date_from, date_to = filters.from_date, filters.to_date
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    def key_list(values: list[str] | None) -> list[str] | None:
        if not values:
            return None
        out = [normalize_sector_key(v) for v in values]
        out = [v for v in out if v and v != "all"]
        return out or None

    limit = filters.limit if filters.limit and 0 < filters.limit <= MAX_ROWS_RETURNED else PAGE_SIZE
    offset = filters.offset if filters.offset and filters.offset > 0 else 0

    return HistoryFilters(
        from_date=date_from, to_date=date_to,
        sectors=key_list(filters.sectors), priorities=key_list(filters.priorities), purities=key_list(filters.purities),
        status=filters.status if filters.status in {"all", "pending", "cleared", "allocated", "unallocated"} else "all",
        limit=limit, offset=offset,
    )


def _paginate(rows: list, limit: int, offset: int) -> tuple[list, PageInfo]:
    """Legacy paginate_() — paging is done on the server so the browser never
    holds the whole history."""
    total = len(rows)
    page_size = max(limit, 1)
    total_pages = max(1, math.ceil(total / page_size))
    current_page = min(offset // page_size + 1, total_pages)
    start = (current_page - 1) * page_size
    page_rows = rows[start : start + page_size]
    return page_rows, PageInfo(
        current_page=current_page, total_pages=total_pages, page_size=page_size, offset=start,
        total_records=total, first_record=(start + 1) if total else 0, last_record=start + len(page_rows),
        has_previous=current_page > 1, has_next=current_page < total_pages,
    )


def _suggested_range(dates: list[date_], default_days: int) -> tuple[date_ | None, date_ | None]:
    if not dates:
        return None, None
    latest = dates[-1]
    suggested_from = latest - timedelta(days=default_days - 1)
    if suggested_from < dates[0]:
        suggested_from = dates[0]
    return suggested_from, latest


def get_history_filter_options(db: Session, scope: UserScope) -> HistoryFilterOptionsOut:
    """Legacy getHistoryFilterOptions()."""
    party_keys = _require_scope(scope)

    master_rows = allocation_repo.list_for_history(
        db, date_from=None, date_to=None, sector_keys=None, priority_keys=None, purity_keys=None, party_keys=party_keys
    )
    flow_rows = flow_repo.list_for_history(db, date_from=None, date_to=None, sector_keys=None, party_keys=party_keys)

    alloc_defs = scoped_allocation_sectors(db, scope)
    flow_defs = scoped_flow_sectors(db, scope)

    alloc_seen = {d.sector_key for d in alloc_defs}
    alloc_options = [SectorOption(sector=d.sector_name, key=d.sector_key, active=True) for d in alloc_defs]
    flow_seen = {d.sector_key for d in flow_defs}
    flow_options = [SectorOption(sector=d.sector_name, key=d.sector_key, active=True) for d in flow_defs]

    priority_seen: dict[str, str] = {}
    purity_seen: dict[str, str] = {}
    date_seen: set[date_] = set()

    for r in master_rows:
        if r.sector.sector_key not in alloc_seen:
            alloc_seen.add(r.sector.sector_key)
            alloc_options.append(SectorOption(sector=r.sector.sector_name, key=r.sector.sector_key, active=False))
        pk = normalize_sector_key(r.priority)
        if pk and pk not in priority_seen:
            priority_seen[pk] = r.priority
        uk = normalize_sector_key(r.purity)
        if uk and uk not in purity_seen:
            purity_seen[uk] = r.purity
        date_seen.add(r.allocation_date)

    for r in flow_rows:
        if r.flow_sector.sector_key not in flow_seen:
            flow_seen.add(r.flow_sector.sector_key)
            flow_options.append(SectorOption(sector=r.flow_sector.sector_name, key=r.flow_sector.sector_key, active=False))
        date_seen.add(r.flow_date)

    dates_sorted = sorted(date_seen)
    suggested_from, suggested_to = _suggested_range(dates_sorted, DEFAULT_RANGE_DAYS)

    return HistoryFilterOptionsOut(
        allocation_sectors=alloc_options, flow_sectors=flow_options,
        priorities=[LabelledOption(label=v, key=k) for k, v in sorted(priority_seen.items())],
        purities=[LabelledOption(label=v, key=k) for k, v in sorted(purity_seen.items())],
        saved_date_count=len(dates_sorted), min_date=dates_sorted[0] if dates_sorted else None, max_date=suggested_to,
        suggested_from=suggested_from, suggested_to=suggested_to,
        allocation_record_count=len(master_rows), flow_record_count=len(flow_rows),
    )


def get_allocation_history(db: Session, scope: UserScope, filters: HistoryFilters) -> AllocationHistoryOut:
    """Legacy getAllocationHistory()."""
    nf = _normalize_filters(filters)
    party_keys = _require_scope(scope)

    rows = allocation_repo.list_for_history(
        db, date_from=nf.from_date, date_to=nf.to_date, sector_keys=nf.sectors,
        priority_keys=nf.priorities, purity_keys=nf.purities, party_keys=party_keys,
    )

    if nf.status == "pending":
        rows = [r for r in rows if r.balance > 0]
    elif nf.status == "cleared":
        rows = [r for r in rows if not (r.balance > 0)]
    elif nf.status == "allocated":
        rows = [r for r in rows if r.alloted > 0]
    elif nf.status == "unallocated":
        rows = [r for r in rows if not (r.alloted > 0)]

    order_map = {d.sector_key: i for i, d in enumerate(sector_repo.list_allocation_sectors(db))}

    total_prev = total_today = total_alloted = total_balance = Decimal("0")
    date_seen: set[date_] = set()
    sector_seen: set[str] = set()
    for r in rows:
        total_prev += r.previous_requirement
        total_today += r.today_required
        total_alloted += r.alloted
        total_balance += r.balance
        date_seen.add(r.allocation_date)
        sector_seen.add(r.sector.sector_key)
    total_prev, total_today, total_alloted, total_balance = (
        round3(total_prev), round3(total_today), round3(total_alloted), round3(total_balance)
    )

    rows.sort(key=lambda r: (-r.allocation_date.toordinal(), order_map.get(r.sector.sector_key, 999), r.sector.sector_name))
    page, page_info = _paginate(rows, nf.limit, nf.offset)

    by_day: dict[date_, Decimal] = {}
    for r in rows:
        by_day[r.allocation_date] = by_day.get(r.allocation_date, Decimal("0")) + r.balance
    peak_key, peak_val = None, Decimal("0")
    for k, v in by_day.items():
        if peak_key is None or v > peak_val:
            peak_key, peak_val = k, v

    total_demand = round3(total_prev + total_today)
    fulfilment = round3((total_alloted / total_demand) * 100) if total_demand > 0 else Decimal("0")

    return AllocationHistoryOut(
        rows=[
            AllocationHistoryRowOut(
                date_key=r.allocation_date, date_display=format_display_date(r.allocation_date), priority=r.priority,
                sector=r.sector.sector_name, purity=r.purity, previous_requirement=r.previous_requirement,
                today_required=r.today_required, alloted=r.alloted, balance=r.balance,
            )
            for r in page
        ],
        summary=AllocationHistorySummaryOut(
            record_count=len(rows), returned_count=len(page), truncated=False,
            date_count=len(date_seen), sector_count=len(sector_seen),
            total_previous_requirement=total_prev, total_today_required=total_today,
            total_alloted=total_alloted, total_balance=total_balance,
            peak_balance=PeakBalanceOut(value=round3(peak_val), date_display=format_display_date(peak_key) if peak_key else ""),
            total_demand=total_demand, fulfilment_rate=fulfilment,
        ),
        page=page_info,
    )


def _limit_flow_to_window(rows: list) -> list:
    """Legacy limitFlowToWindow_() — calendar-based 30-day window for the heatmap only."""
    if not rows:
        return rows
    newest = max(r.flow_date for r in rows)
    cutoff = newest - timedelta(days=HEATMAP_WINDOW_DAYS - 1)
    return [r for r in rows if r.flow_date >= cutoff]


def _build_flow_series(rows: list) -> FlowSeriesOut:
    """Legacy buildFlowSeries_()."""
    date_keys: list[date_] = []
    date_seen: set[date_] = set()
    sector_total: dict[str, Decimal] = {}
    cell: dict[tuple[date_, str], Decimal] = {}
    grand_total = Decimal("0")

    for r in rows:
        if r.flow_date not in date_seen:
            date_seen.add(r.flow_date)
            date_keys.append(r.flow_date)
        name = r.flow_sector.sector_name
        cell[(r.flow_date, name)] = cell.get((r.flow_date, name), Decimal("0")) + r.acquired
        sector_total[name] = sector_total.get(name, Decimal("0")) + r.acquired
        grand_total += r.acquired

    date_keys.sort()
    grand_total = round3(grand_total)

    names = [n for n, t in sector_total.items() if round3(t) > 0]
    names.sort(key=lambda n: (-sector_total[n], n))

    sectors = [
        FlowSeriesSectorOut(
            sector=name, total=round3(sector_total[name]),
            percent=round3((sector_total[name] / grand_total) * 100) if grand_total > 0 else Decimal("0"),
            values=[round3(cell.get((dk, name), Decimal("0"))) for dk in date_keys],
        )
        for name in names
    ]

    return FlowSeriesOut(
        dates=date_keys, displays=[format_display_date(dk) for dk in date_keys], sectors=sectors, grand_total=grand_total
    )


def _build_flow_heatmap(rows: list) -> HeatmapOut:
    """Legacy buildFlowHeatmap_()."""
    date_seen: set[date_] = set()
    date_keys: list[date_] = []
    sector_name: dict[str, str] = {}
    sector_total: dict[str, Decimal] = {}
    cell_map: dict[tuple[date_, str], Decimal] = {}
    record_count = 0
    total_acquired = Decimal("0")

    for r in rows:
        dk, sk = r.flow_date, r.flow_sector.sector_key
        if dk not in date_seen:
            date_seen.add(dk)
            date_keys.append(dk)
        if sk not in sector_name:
            sector_name[sk] = r.flow_sector.sector_name
            sector_total[sk] = Decimal("0")
        cell_map[(dk, sk)] = cell_map.get((dk, sk), Decimal("0")) + r.acquired
        sector_total[sk] += r.acquired
        total_acquired += r.acquired
        record_count += 1

    date_keys.sort()
    truncated = False
    if len(date_keys) > MAX_HEATMAP_DATES:
        date_keys = date_keys[-MAX_HEATMAP_DATES:]
        truncated = True

    sector_keys = [sk for sk in sector_name if round3(sector_total[sk]) > 0]
    sector_keys.sort(key=lambda sk: (-sector_total[sk], sector_name[sk]))

    dates = [
        {"date_key": dk, "date_label": short_date_label(dk), "full_date_label": format_display_date(dk)}
        for dk in date_keys
    ]

    cells: list[HeatmapCellOut] = []
    maximum_acquired = Decimal("0")
    peak = HeatmapPeakOut()
    day_total: dict[date_, Decimal] = {}

    for d in dates:
        for sk in sector_keys:
            v = round3(cell_map.get((d["date_key"], sk), Decimal("0")))
            cells.append(
                HeatmapCellOut(
                    date_key=d["date_key"], date_label=d["date_label"], full_date_label=d["full_date_label"],
                    sector=sector_name[sk], acquired=v,
                )
            )
            day_total[d["date_key"]] = day_total.get(d["date_key"], Decimal("0")) + v
            if v > maximum_acquired:
                maximum_acquired = v
                peak = HeatmapPeakOut(acquired=v, sector=sector_name[sk], date_label=d["date_label"], full_date_label=d["full_date_label"])

    busiest_day = {"date_key": "", "full_date_label": "", "acquired": "0.000"}
    best_total = Decimal("0")
    for d in dates:
        t = day_total.get(d["date_key"], Decimal("0"))
        if t > best_total:
            best_total = t
            busiest_day = {"date_key": d["date_key"].isoformat(), "full_date_label": d["full_date_label"], "acquired": str(t)}

    total_acquired = round3(total_acquired)
    most_active = HeatmapMostActiveOut()
    if sector_keys:
        top = sector_keys[0]
        most_active = HeatmapMostActiveOut(
            sector=sector_name[top], total=round3(sector_total[top]),
            percent=round3((sector_total[top] / total_acquired) * 100) if total_acquired > 0 else Decimal("0"),
        )

    return HeatmapOut(
        dates=[{"date_key": d["date_key"].isoformat(), "date_label": d["date_label"], "full_date_label": d["full_date_label"]} for d in dates],
        sectors=[sector_name[sk] for sk in sector_keys], cells=cells, maximum_acquired=maximum_acquired,
        record_count=record_count, total_acquired=total_acquired, date_count=len(dates), party_count=len(sector_keys),
        peak=peak, busiest_day=busiest_day, most_active=most_active, truncated=truncated, window_days=HEATMAP_WINDOW_DAYS,
        truncation_note=(f"Showing the most recent {MAX_HEATMAP_DATES} dates. Narrow the range to see earlier dates." if truncated else ""),
    )


def _cycle_comparison(rows_by_day: dict[date_, Decimal]) -> CycleComparisonOut:
    """
    Legacy's "versus previous cycle" comparison (duplicated in
    getMetalFlowHistory and getDashboardSummary — unified here). Splits the
    dates in range down the middle; with an odd count the extra date joins
    the current half, which never inflates the change. null below four dates
    or when the older half acquired nothing.
    """
    keys = sorted(rows_by_day.keys())
    half = len(keys) // 2
    if len(keys) < 4:
        return CycleComparisonOut(day_count=half, change_percent=None)
    prev_sum = sum((rows_by_day[k] for k in keys[:half]), Decimal("0"))
    curr_sum = sum((rows_by_day[k] for k in keys[half:]), Decimal("0"))
    change = round3(((curr_sum - prev_sum) / prev_sum) * 100) if prev_sum > 0 else None
    return CycleComparisonOut(
        previous_acquired=round3(prev_sum), current_acquired=round3(curr_sum), day_count=half, change_percent=change
    )


def get_metal_flow_history(db: Session, scope: UserScope, filters: HistoryFilters) -> FlowHistoryOut:
    """Legacy getMetalFlowHistory()."""
    nf = _normalize_filters(filters)
    party_keys = _require_scope(scope)

    rows = flow_repo.list_for_history(db, date_from=nf.from_date, date_to=nf.to_date, sector_keys=nf.sectors, party_keys=party_keys)
    if nf.status == "allocated":
        rows = [r for r in rows if r.acquired > 0]
    elif nf.status == "unallocated":
        rows = [r for r in rows if not (r.acquired > 0)]

    order_map = {d.sector_key: i for i, d in enumerate(sector_repo.list_flow_sectors(db))}

    total_acquired = Decimal("0")
    date_seen: set[date_] = set()
    sector_seen: set[str] = set()
    for r in rows:
        total_acquired += r.acquired
        date_seen.add(r.flow_date)
        sector_seen.add(r.flow_sector.sector_key)
    total_acquired = round3(total_acquired)

    rows.sort(key=lambda r: (-r.flow_date.toordinal(), order_map.get(r.flow_sector.sector_key, 999), r.flow_sector.sector_name))
    page, page_info = _paginate(rows, nf.limit, nf.offset)

    series = _build_flow_series(rows)
    heatmap = _build_flow_heatmap(_limit_flow_to_window(rows))

    by_day: dict[date_, Decimal] = {}
    for r in rows:
        by_day[r.flow_date] = by_day.get(r.flow_date, Decimal("0")) + r.acquired

    return FlowHistoryOut(
        rows=[
            FlowHistoryRowOut(date_key=r.flow_date, date_display=format_display_date(r.flow_date), sector=r.flow_sector.sector_name, acquired=r.acquired)
            for r in page
        ],
        summary=FlowHistorySummaryOut(
            record_count=len(rows), returned_count=len(page), truncated=False,
            date_count=len(date_seen), sector_count=len(sector_seen), total_acquired=total_acquired,
            average_per_day=round3(total_acquired / len(date_seen)) if date_seen else Decimal("0"),
            cycle=_cycle_comparison(by_day),
        ),
        series=series, heatmap=heatmap, page=page_info,
    )


def get_dashboard_summary(db: Session, scope: UserScope, filters: HistoryFilters) -> DashboardSummaryOut:
    """Legacy getDashboardSummary()."""
    nf = _normalize_filters(filters)
    party_keys = _require_scope(scope)

    alloc_rows = allocation_repo.list_for_history(
        db, date_from=nf.from_date, date_to=nf.to_date, sector_keys=nf.sectors,
        priority_keys=nf.priorities, purity_keys=None, party_keys=party_keys,
    )
    flow_rows_all = flow_repo.list_for_history(db, date_from=nf.from_date, date_to=nf.to_date, sector_keys=None, party_keys=party_keys)

    # Metal Flow has its own sector list, so an allocation-sector filter must
    # not silently blank the acquired series — it only applies to flow when
    # the selected key actually exists in the flow master.
    flow_keys_present = {r.flow_sector.sector_key for r in flow_rows_all}
    flow_filter_active = bool(nf.sectors and any(k in flow_keys_present for k in nf.sectors))
    flow_rows = [r for r in flow_rows_all if not flow_filter_active or r.flow_sector.sector_key in nf.sectors]

    by_date_map: dict[date_, dict] = {}

    def bucket(k: date_) -> dict:
        return by_date_map.setdefault(
            k, {"previous_requirement": Decimal("0"), "required": Decimal("0"), "alloted": Decimal("0"), "balance": Decimal("0"), "acquired": Decimal("0")}
        )

    for r in alloc_rows:
        b = bucket(r.allocation_date)
        b["previous_requirement"] += r.previous_requirement
        b["required"] += r.today_required
        b["alloted"] += r.alloted
        b["balance"] += r.balance
    for r in flow_rows:
        bucket(r.flow_date)["acquired"] += r.acquired

    by_date: list[DashboardByDateOut] = []
    for k in sorted(by_date_map.keys()):
        b = by_date_map[k]
        acquired, alloted = round3(b["acquired"]), round3(b["alloted"])
        by_date.append(
            DashboardByDateOut(
                date_key=k, date_display=format_display_date(k), previous_requirement=round3(b["previous_requirement"]),
                required=round3(b["required"]), alloted=alloted, balance=round3(b["balance"]), acquired=acquired,
                unallocated=round3(max(Decimal("0"), acquired - alloted)),
                utilisation=round3((alloted / acquired) * 100) if acquired > 0 else Decimal("0"),
            )
        )
    if len(by_date) > MAX_TREND_POINTS:
        by_date = by_date[-MAX_TREND_POINTS:]

    by_sector_map: dict[str, dict] = {}
    for r in alloc_rows:
        sk = r.sector.sector_key
        entry = by_sector_map.setdefault(
            sk, {"sector": r.sector.sector_name, "priority": r.priority, "required": Decimal("0"), "alloted": Decimal("0"), "balance": Decimal("0"), "latest_balance": Decimal("0"), "latest_date": None}
        )
        entry["required"] += r.today_required
        entry["alloted"] += r.alloted
        entry["balance"] += r.balance
        if not entry["latest_date"] or r.allocation_date > entry["latest_date"]:
            entry["latest_date"] = r.allocation_date
            entry["latest_balance"] = r.balance
            entry["priority"] = r.priority

    by_sector = [
        DashboardBySectorOut(
            sector=b["sector"], priority=b["priority"], required=round3(b["required"]), alloted=round3(b["alloted"]),
            balance=round3(b["balance"]), latest_balance=round3(b["latest_balance"]),
            latest_date_display=format_display_date(b["latest_date"]) if b["latest_date"] else "",
        )
        for b in by_sector_map.values()
    ]
    by_sector.sort(key=lambda x: -x.required)

    by_priority_map: dict[str, dict] = {}
    grand_alloted = Decimal("0")
    for r in alloc_rows:
        label = r.priority or "Unspecified"
        entry = by_priority_map.setdefault(label, {"alloted": Decimal("0"), "required": Decimal("0"), "balance": Decimal("0")})
        entry["alloted"] += r.alloted
        entry["required"] += r.today_required
        entry["balance"] += r.balance
        grand_alloted += r.alloted
    grand_alloted = round3(grand_alloted)

    by_priority = [
        DashboardByPriorityOut(
            priority=label, alloted=round3(by_priority_map[label]["alloted"]), required=round3(by_priority_map[label]["required"]),
            balance=round3(by_priority_map[label]["balance"]),
            share=round3((by_priority_map[label]["alloted"] / grand_alloted) * 100) if grand_alloted > 0 else Decimal("0"),
        )
        for label in sorted(by_priority_map.keys())
    ]

    top_pending = [
        TopPendingOut(sector=b["sector"], priority=b["priority"], pending=round3(b["latest_balance"]), as_of=format_display_date(b["latest_date"]) if b["latest_date"] else "")
        for b in by_sector_map.values()
    ]
    top_pending = [t for t in top_pending if t.pending > 0]
    top_pending.sort(key=lambda t: -t.pending)
    top_pending = top_pending[:TOP_SECTOR_LIMIT]

    total_acquired = sum((b.acquired for b in by_date), Decimal("0"))
    total_alloted = sum((b.alloted for b in by_date), Decimal("0"))
    total_required = sum((b.required for b in by_date), Decimal("0"))
    latest = by_date[-1] if by_date else None
    total_pending_now = sum((t.pending for t in top_pending), Decimal("0"))

    by_day_acquired = {d.date_key: d.acquired for d in by_date}
    cycle = _cycle_comparison(by_day_acquired)

    peak_balance, peak_date_display = Decimal("0"), ""
    peak_seen = False
    for d in by_date:
        if not peak_seen or d.balance > peak_balance:
            peak_balance, peak_date_display, peak_seen = d.balance, d.date_display, True

    kpis = DashboardKpisOut(
        day_count=len(by_date), total_acquired=round3(total_acquired), total_alloted=round3(total_alloted),
        total_required=round3(total_required), unallocated=round3(max(Decimal("0"), total_acquired - total_alloted)),
        utilisation=round3((total_alloted / total_acquired) * 100) if total_acquired > 0 else Decimal("0"),
        average_daily_acquired=round3(total_acquired / len(by_date)) if by_date else Decimal("0"),
        latest_date=latest.date_key if latest else None, latest_date_display=latest.date_display if latest else "",
        latest_closing_balance=latest.balance if latest else Decimal("0"),
        pending_sector_count=len(top_pending), total_pending_latest=round3(total_pending_now),
        fulfilment_rate=round3((total_alloted / total_required) * 100) if total_required > 0 else Decimal("0"),
        previous_cycle_acquired=cycle.previous_acquired or Decimal("0"),
        current_cycle_acquired=cycle.current_acquired or Decimal("0"),
        acquired_change_percent=cycle.change_percent, cycle_day_count=cycle.day_count,
        peak_closing_balance=round3(peak_balance), peak_closing_date=peak_date_display,
    )

    return DashboardSummaryOut(
        kpis=kpis, heatmap=_build_flow_heatmap(flow_rows), by_date=by_date, by_sector=by_sector,
        by_priority=by_priority, top_pending=top_pending,
    )
