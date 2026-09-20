"""schemas/report.py — history and dashboard responses.

Weights cross as kilogram strings (`Decimal`), converted from integer grams.
Only rows the caller may see are ever included; the scoping happens in SQL.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class AllocationHistoryRow(BaseModel):
    allocation_date: date
    # 'Tue, 08-Sep-2026' — legacy's formatDisplayDate_() form.
    date_display: str
    sector_name: str
    party_name: str
    priority: str
    purity: str
    previous_requirement_kg: Decimal
    today_required_kg: Decimal
    alloted_kg: Decimal
    balance_kg: Decimal
    revision_number: int


class PeakBalance(BaseModel):
    value_kg: Decimal
    date_display: str | None


class AllocationHistorySummary(BaseModel):
    record_count: int
    returned_count: int
    truncated: bool
    date_count: int
    sector_count: int
    total_previous_requirement_kg: Decimal
    total_today_required_kg: Decimal
    total_alloted_kg: Decimal
    total_balance_kg: Decimal
    total_demand_kg: Decimal
    # alloted / (previous_requirement + today_required) * 100.
    # 0 when demand <= 0 — a negative previous requirement means the sector was
    # over-allocated earlier and is carrying credit.
    fulfilment_rate: float
    peak_balance: PeakBalance


class PageInfo(BaseModel):
    current_page: int
    total_pages: int
    page_size: int
    offset: int
    total_records: int
    first_record: int
    last_record: int
    has_previous: bool
    has_next: bool


class AllocationHistoryResponse(BaseModel):
    rows: list[AllocationHistoryRow]
    total_rows: int
    summary: AllocationHistorySummary
    page: PageInfo


class FlowHistoryRow(BaseModel):
    allocation_date: date
    sector_name: str
    party_name: str
    acquired_kg: Decimal
    revision_number: int


class FlowHistoryResponse(BaseModel):
    rows: list[FlowHistoryRow]
    total_rows: int


class DatePoint(BaseModel):
    allocation_date: date
    previous_requirement_kg: Decimal
    today_required_kg: Decimal
    alloted_kg: Decimal
    balance_kg: Decimal
    acquired_kg: Decimal


class SectorPoint(BaseModel):
    sector_name: str
    priority: str
    today_required_kg: Decimal
    alloted_kg: Decimal
    balance_kg: Decimal


class PriorityPoint(BaseModel):
    priority: str
    today_required_kg: Decimal
    alloted_kg: Decimal
    balance_kg: Decimal


class CycleDelta(BaseModel):
    """Splits the saved dates in range down the middle and compares the newer
    half against the older. An odd count puts the extra date in the CURRENT
    half, which never inflates the change."""

    previous_acquired_kg: Decimal
    current_acquired_kg: Decimal
    day_count: int
    # None below four dates, or when the older half acquired nothing — a change
    # from zero is undefined, not infinite.
    change_percent: float | None


class TopPendingPoint(BaseModel):
    sector_name: str
    priority: str
    pending_kg: Decimal
    as_of: date
    as_of_display: str


class DashboardResponse(BaseModel):
    # --- the six KPI cards ---
    saved_days: int
    latest_saved_date: date | None
    latest_saved_date_display: str | None
    utilisation_rate: float | None
    average_daily_acquired_kg: Decimal
    by_date: list[DatePoint]
    by_sector: list[SectorPoint]
    by_priority: list[PriorityPoint]
    total_acquired_kg: Decimal
    total_alloted_kg: Decimal
    total_required_kg: Decimal
    closing_balance_kg: Decimal
    saved_date_count: int
    peak_closing_balance_kg: Decimal
    peak_closing_date: date | None
    peak_closing_date_display: str | None
    fulfilment_rate: float | None
    cycle: CycleDelta
    top_pending: list[TopPendingPoint]
    # Drives the operator-only "Your Metal Flow Trend" card. Resolved here, never
    # taken from the browser (rule 8).
    is_admin: bool
    # A sector filter was asked for but not applied to the supply side, because
    # that name has no records in the flow ledger (page spec, rule 2).
    flow_filter_skipped: bool


# --------------------------------------------------------------- Metal Flow


class HeatmapDate(BaseModel):
    date_key: date
    short_label: str
    full_label: str


class HeatmapCell(BaseModel):
    date_key: date
    flow_sector_id: int
    acquired_kg: Decimal


class HeatmapSector(BaseModel):
    flow_sector_id: int
    sector_name: str
    total_kg: Decimal


class FlowSeriesSector(BaseModel):
    sector_name: str
    total_kg: Decimal
    percent: float


class FlowHeatmap(BaseModel):
    dates: list[HeatmapDate]
    sectors: list[HeatmapSector]
    cells: list[HeatmapCell]
    max_acquired_kg: Decimal
    truncated: bool
    truncation_note: str | None
    window_days: int
    peak: "FlowPeak"
    most_active: "FlowMostActive"
    # The highest day TOTAL. Computed and returned; the KPI card shows `peak`.
    busiest_day_kg: Decimal
    busiest_day_label: str | None


class FlowPeak(BaseModel):
    """The largest single CELL — one sector on one date — not the largest day
    total. The day total is `busiest_day_kg`, returned but not displayed."""

    acquired_kg: Decimal
    sector_name: str | None
    full_date_label: str | None


class FlowMostActive(BaseModel):
    sector_name: str | None
    total_kg: Decimal
    percent: float


class FlowSummary(BaseModel):
    record_count: int
    date_count: int
    sector_count: int
    total_sector_count: int
    total_acquired_kg: Decimal
    # totalAcquired / dateCount — dates WITH records, not calendar days.
    average_per_day_kg: Decimal
    cycle: CycleDelta


class FlowAnalysisResponse(BaseModel):
    summary: FlowSummary
    heatmap: FlowHeatmap


class NavCounts(BaseModel):
    allocation_history: int
    flow_history: int
    audit: int
