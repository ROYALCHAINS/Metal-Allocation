"""
schemas/allocation.py — the Daily Allocation screen model as sent to the client.

Weights cross this boundary as KILOGRAMS (`Decimal`, 3 decimals), converted from
the integer grams held in the database by services/weight_service.py. The `_kg`
suffix mirrors the database's `_g` suffix so the unit is never ambiguous.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from schemas.audit import DateRevisionSummaryResponse
from schemas.staging import SubmissionSummaryRow


class AllocationRowResponse(BaseModel):
    sector_id: int
    sector_name: str
    priority: str
    purity: str
    party_name: str
    previous_requirement_kg: Decimal
    today_required_kg: Decimal
    alloted_kg: Decimal
    balance_kg: Decimal
    # True when this figure came from an operator submission rather than the
    # saved ledger, so the screen can mark it as somebody else's input.
    from_submission: bool = False


class FlowRowResponse(BaseModel):
    flow_sector_id: int
    sector_name: str
    party_name: str
    previous_acquired_kg: Decimal
    today_acquired_kg: Decimal
    from_submission: bool = False


class TotalsResponse(BaseModel):
    total_previous_requirement_kg: Decimal
    total_today_required_kg: Decimal
    total_alloted_kg: Decimal
    total_balance_kg: Decimal
    total_acquired_kg: Decimal
    remaining_to_allocate_kg: Decimal


class AllocationRowInput(BaseModel):
    """One submitted allocation row.

    Only the three weights are accepted. Sector name, party, purity and priority
    are taken from the database on the server — never from the client — so a
    tampered payload cannot rename a sector or move it to another party.
    """

    sector_id: int
    previous_requirement_kg: Decimal
    today_required_kg: Decimal
    alloted_kg: Decimal


class FlowRowInput(BaseModel):
    flow_sector_id: int
    today_acquired_kg: Decimal


class SaveAllocationRequest(BaseModel):
    allocations: list[AllocationRowInput]
    metal_flow: list[FlowRowInput]
    # Client-generated; a repeat within 900 seconds must not write twice
    # (CLAUDE.md section 6, rule 12).
    request_id: str


class SaveAllocationResponse(BaseModel):
    allocation_date: date
    allocation_records: int
    flow_records: int
    audit_id: str
    request_id: str
    totals: "TotalsResponse"


class AllocationModelResponse(BaseModel):
    selected_date: date
    selected_date_display: str
    rule_source_date: date
    rule_source_date_display: str
    previous_source_date: date
    previous_source_date_display: str
    # True when the rule date had nothing saved and an older date was used.
    used_fallback_source: bool
    has_previous_data: bool
    is_saved: bool
    allocations: list[AllocationRowResponse]
    metal_flow: list[FlowRowResponse]
    totals: TotalsResponse
    total_previous_acquired_kg: Decimal
    # An operator whose party has submitted sees their figures, locked.
    already_submitted: bool = False
    # How many fields on this screen came from an operator submission.
    staged_value_count: int = 0
    # Who submitted for this date and when. ADMINISTRATORS ONLY — an operator
    # receives an empty list even for their own submission. Note this is a list
    # of submissions, while staged_value_count above counts fields.
    submissions: list[SubmissionSummaryRow] = Field(default_factory=list)
    # Who committed this date and whether it has been revised. Operator-visible
    # by design — unlike `submissions` above, this is NOT admin-only.
    revision_summary: DateRevisionSummaryResponse | None = None
    can_submit: bool = False
