"""schemas/staging.py — the operator submission path.

Operators submit Today's Required per allocation sector and Today's Acquired
per Metal Flow party. They never submit `alloted` or `balance`: allotment is the
administrator's decision and balance is computed on save, never accepted from a
client.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class StagedAllocationInput(BaseModel):
    sector_id: int
    today_required_kg: Decimal


class StagedFlowInput(BaseModel):
    flow_sector_id: int
    today_acquired_kg: Decimal


class SubmitRequirementRequest(BaseModel):
    allocations: list[StagedAllocationInput] = Field(default_factory=list)
    metal_flow: list[StagedFlowInput] = Field(default_factory=list)
    # Guards a double-click, the same way the save path does.
    request_id: str


class SubmitRequirementResponse(BaseModel):
    allocation_date: date
    submission_id: str
    allocation_records: int
    flow_records: int
    total_required_kg: Decimal
    total_acquired_kg: Decimal
    audit_id: str


class SubmissionSummaryRow(BaseModel):
    operator_email: str
    party_name: str
    submitted_at: str
    record_count: int


class StagingStatusResponse(BaseModel):
    """What the screen needs to decide whether the inputs are editable."""

    allocation_date: date
    # True once THIS user's parties have a pending submission — the inputs lock.
    already_submitted: bool
    # True once the administrator has committed the date; nothing is editable.
    is_saved: bool
    can_submit: bool
    submissions: list[SubmissionSummaryRow]
