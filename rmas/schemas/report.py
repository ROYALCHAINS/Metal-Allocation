"""
schemas/report.py — Allocation History, Metal Flow History, Analysis
Dashboard shapes. Legacy: ReportService.gs.
"""

from datetime import date as date_
from decimal import Decimal

from pydantic import BaseModel, Field

from rmas.schemas.common import PageInfo


class HistoryFilters(BaseModel):
    from_date: date_ | None = None
    to_date: date_ | None = None
    sectors: list[str] | None = None
    priorities: list[str] | None = None
    purities: list[str] | None = None
    status: str = "all"  # all | pending | cleared | allocated | unallocated
    limit: int = 100
    offset: int = 0


class SectorOption(BaseModel):
    sector: str
    key: str
    active: bool


class LabelledOption(BaseModel):
    label: str
    key: str


class HistoryFilterOptionsOut(BaseModel):
    allocation_sectors: list[SectorOption]
    flow_sectors: list[SectorOption]
    priorities: list[LabelledOption]
    purities: list[LabelledOption]
    saved_date_count: int
    min_date: date_ | None
    max_date: date_ | None
    suggested_from: date_ | None
    suggested_to: date_ | None
    allocation_record_count: int
    flow_record_count: int


class AllocationHistoryRowOut(BaseModel):
    date_key: date_
    date_display: str
    priority: str
    sector: str
    purity: str
    previous_requirement: Decimal
    today_required: Decimal
    alloted: Decimal
    balance: Decimal


class PeakBalanceOut(BaseModel):
    value: Decimal
    date_display: str


class AllocationHistorySummaryOut(BaseModel):
    record_count: int
    returned_count: int
    truncated: bool
    date_count: int
    sector_count: int
    total_previous_requirement: Decimal
    total_today_required: Decimal
    total_alloted: Decimal
    total_balance: Decimal
    peak_balance: PeakBalanceOut
    total_demand: Decimal
    fulfilment_rate: Decimal


class AllocationHistoryOut(BaseModel):
    rows: list[AllocationHistoryRowOut]
    summary: AllocationHistorySummaryOut
    page: PageInfo


class FlowHistoryRowOut(BaseModel):
    date_key: date_
    date_display: str
    sector: str
    acquired: Decimal


class CycleComparisonOut(BaseModel):
    previous_acquired: Decimal | None = None
    current_acquired: Decimal | None = None
    day_count: int
    change_percent: Decimal | None = None


class FlowHistorySummaryOut(BaseModel):
    record_count: int
    returned_count: int
    truncated: bool
    date_count: int
    sector_count: int
    total_acquired: Decimal
    average_per_day: Decimal
    cycle: CycleComparisonOut


class FlowSeriesSectorOut(BaseModel):
    sector: str
    total: Decimal
    percent: Decimal
    values: list[Decimal]


class FlowSeriesOut(BaseModel):
    dates: list[date_]
    displays: list[str]
    sectors: list[FlowSeriesSectorOut]
    grand_total: Decimal


class HeatmapCellOut(BaseModel):
    date_key: date_
    date_label: str
    full_date_label: str
    sector: str
    acquired: Decimal


class HeatmapPeakOut(BaseModel):
    acquired: Decimal = Decimal("0")
    sector: str = ""
    date_label: str = ""
    full_date_label: str = ""


class HeatmapMostActiveOut(BaseModel):
    sector: str = ""
    total: Decimal = Decimal("0")
    percent: Decimal = Decimal("0")


class HeatmapOut(BaseModel):
    dates: list[dict]
    sectors: list[str]
    cells: list[HeatmapCellOut]
    maximum_acquired: Decimal
    record_count: int
    total_acquired: Decimal
    date_count: int
    party_count: int
    peak: HeatmapPeakOut
    busiest_day: dict
    most_active: HeatmapMostActiveOut
    truncated: bool
    window_days: int
    truncation_note: str = ""


class FlowHistoryOut(BaseModel):
    rows: list[FlowHistoryRowOut]
    summary: FlowHistorySummaryOut
    series: FlowSeriesOut
    heatmap: HeatmapOut
    page: PageInfo


class DashboardByDateOut(BaseModel):
    date_key: date_
    date_display: str
    previous_requirement: Decimal
    required: Decimal
    alloted: Decimal
    balance: Decimal
    acquired: Decimal
    unallocated: Decimal
    utilisation: Decimal


class DashboardBySectorOut(BaseModel):
    sector: str
    priority: str
    required: Decimal
    alloted: Decimal
    balance: Decimal
    latest_balance: Decimal
    latest_date_display: str


class DashboardByPriorityOut(BaseModel):
    priority: str
    alloted: Decimal
    required: Decimal
    balance: Decimal
    share: Decimal


class TopPendingOut(BaseModel):
    sector: str
    priority: str
    pending: Decimal
    as_of: str


class DashboardKpisOut(BaseModel):
    day_count: int
    total_acquired: Decimal
    total_alloted: Decimal
    total_required: Decimal
    unallocated: Decimal
    utilisation: Decimal
    average_daily_acquired: Decimal
    latest_date: date_ | None
    latest_date_display: str
    latest_closing_balance: Decimal
    pending_sector_count: int
    total_pending_latest: Decimal
    fulfilment_rate: Decimal
    previous_cycle_acquired: Decimal
    current_cycle_acquired: Decimal
    acquired_change_percent: Decimal | None
    cycle_day_count: int
    peak_closing_balance: Decimal
    peak_closing_date: str


class DashboardSummaryOut(BaseModel):
    kpis: DashboardKpisOut
    heatmap: HeatmapOut
    by_date: list[DashboardByDateOut]
    by_sector: list[DashboardBySectorOut]
    by_priority: list[DashboardByPriorityOut]
    top_pending: list[TopPendingOut] = Field(default_factory=list)
