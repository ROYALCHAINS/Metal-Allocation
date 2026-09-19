"""
schemas/allocation.py — Daily Allocation screen request/response shapes.

Legacy: Code.gs's getAppBootstrapData(), getAllocationForDate(),
saveDailyAllocation(), reviseDailyAllocation() payloads, plus the
DataService.gs buildAllocationModel_() screen model they return.
"""

from datetime import date as date_
from decimal import Decimal

from pydantic import BaseModel, Field

from rmas.schemas.auth import CurrentUserOut
from rmas.schemas.common import PartyOut


class AllocationSectorOut(BaseModel):
    priority: str
    party: str
    sector: str
    purity: str


class FlowSectorOut(BaseModel):
    sector: str
    party: str


class BootstrapConfigOut(BaseModel):
    """Legacy getPublicConfig_() — never includes admin emails."""

    app_name: str
    app_version: str
    decimals: int
    expected_allocation_rows: int
    expected_flow_rows: int
    require_full_allocation: bool
    require_positive_acquired: bool
    min_revision_reason_length: int


class BootstrapOut(BaseModel):
    config: BootstrapConfigOut
    access: CurrentUserOut
    time_zone: str
    today: date_
    parties: list[PartyOut]
    role: str
    allocation_sectors: list[AllocationSectorOut]
    flow_sectors: list[FlowSectorOut]


# ---------------------------------------------------------------- inbound --


class AllocationLineIn(BaseModel):
    sector: str
    priority: str = ""
    purity: str = ""
    previous_requirement: Decimal = Decimal("0")
    today_required: Decimal = Decimal("0")
    alloted: Decimal = Decimal("0")


class FlowLineIn(BaseModel):
    sector: str
    today_acquired: Decimal = Decimal("0")


class SaveAllocationRequest(BaseModel):
    request_id: str
    selected_date: date_
    allocations: list[AllocationLineIn]
    metal_flow: list[FlowLineIn]


class ReviseAllocationRequest(SaveAllocationRequest):
    revision_reason: str


# --------------------------------------------------------------- outbound --


class TotalsOut(BaseModel):
    total_previous_requirement: Decimal
    total_today_required: Decimal
    total_alloted: Decimal
    total_balance: Decimal
    total_acquired: Decimal
    remaining_to_allocate: Decimal


class AllocationLineOut(BaseModel):
    priority: str
    party: str
    sector: str
    purity: str
    previous_requirement: Decimal
    today_required: Decimal
    alloted: Decimal
    balance: Decimal
    from_submission: bool = False


class FlowLineOut(BaseModel):
    sector: str
    party: str
    previous_acquired: Decimal
    today_acquired: Decimal
    from_submission: bool = False


class StagingSubmissionSummaryOut(BaseModel):
    party: str
    operator_email: str
    operator_name: str
    submitted_at: str
    submission_id: str
    total_required: Decimal
    total_acquired: Decimal


class AllocationModelOut(BaseModel):
    selected_date: date_
    selected_date_display: str
    previous_source_date: date_ | None
    previous_source_date_display: str
    rule_source_date: date_
    rule_source_date_display: str
    used_fallback_source: bool
    has_previous_data: bool
    is_saved: bool
    saved_record_count: int
    saved_flow_record_count: int

    allocations: list[AllocationLineOut]
    metal_flow: list[FlowLineOut]
    parties: list[PartyOut]
    totals: TotalsOut
    total_previous_acquired: Decimal

    access: CurrentUserOut
    role: str
    is_operator: bool
    read_only: bool
    can_revise: bool
    can_edit_required: bool
    can_edit_acquired: bool
    can_edit_alloted: bool
    show_global_totals: bool

    is_submitted: bool = False
    submitted_at: str = ""
    submitted_by: str = ""
    staging_submissions: list[StagingSubmissionSummaryOut] = Field(default_factory=list)

    code: str
    message: str


class SaveResultOut(BaseModel):
    selected_date: date_
    selected_date_display: str
    master_records: int
    flow_records: int
    staging_rows_consumed: int
    totals: TotalsOut
    audit_id: str
    request_id: str


class ReviseResultOut(BaseModel):
    selected_date: date_
    revision_number: int
    audit_id: str
    totals: TotalsOut
    request_id: str


class DateAlreadySavedOut(BaseModel):
    selected_date: date_
    is_saved: bool
