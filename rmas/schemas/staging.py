"""
schemas/staging.py — operator submission workflow shapes.

Legacy: StagingService.gs's getOperatorRequirementForDate(),
submitOperatorRequirements(), getStagedRequirementsForDate() payloads.
"""

from datetime import date as date_
from decimal import Decimal

from pydantic import BaseModel, Field

from rmas.schemas.allocation import AllocationLineIn, FlowLineIn
from rmas.schemas.common import PartyOut


class OperatorAllocationLineOut(BaseModel):
    priority: str
    party: str
    sector: str
    purity: str
    previous_requirement: Decimal
    today_required: Decimal
    alloted: Decimal
    balance: Decimal
    is_finalised: bool


class OperatorFlowLineOut(BaseModel):
    sector: str
    party: str
    previous_acquired: Decimal
    today_acquired: Decimal
    is_finalised: bool


class OperatorTotalsOut(BaseModel):
    total_required: Decimal
    total_acquired: Decimal


class OperatorRequirementOut(BaseModel):
    selected_date: date_
    selected_date_display: str
    previous_source_date: date_
    previous_source_date_display: str
    role: str
    parties: list[PartyOut]
    allocations: list[OperatorAllocationLineOut]
    metal_flow: list[OperatorFlowLineOut]
    is_submitted: bool
    is_finalised: bool
    read_only: bool
    submitted_at: str
    submitted_by: str
    submission_id: str
    totals: OperatorTotalsOut
    code: str
    message: str


class SubmitRequirementRequest(BaseModel):
    request_id: str
    selected_date: date_
    allocations: list[AllocationLineIn] = Field(default_factory=list)
    metal_flow: list[FlowLineIn] = Field(default_factory=list)


class SubmitRequirementResultOut(BaseModel):
    submission_id: str
    selected_date: date_
    allocation_records: int
    flow_records: int
    totals: OperatorTotalsOut


class StagedSubmissionOut(BaseModel):
    party: str
    operator_email: str
    operator_name: str
    submitted_at: str
    submission_id: str
    status: str
    total_required: Decimal
    total_acquired: Decimal


class StagedValueOut(BaseModel):
    sector: str
    party: str
    value: Decimal
    has_submission: bool


class StagedRequirementsOut(BaseModel):
    selected_date: date_
    selected_date_display: str
    submissions: list[StagedSubmissionOut]
    pending_parties: list[str]
    allocation_values: list[StagedValueOut]
    flow_values: list[StagedValueOut]
    totals: OperatorTotalsOut
