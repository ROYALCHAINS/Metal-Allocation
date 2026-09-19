"""
dto.py — internal data-transfer objects shared between allocation_service.py
and staging_service.py, so neither has to import the other's module-level
types (avoids a circular import: allocation_service uses staging_service's
overlay function, staging_service mutates allocation_service's model shape).

These are NOT the SQLAlchemy models in rmas/models/, and NOT the Pydantic
request/response schemas in rmas/schemas/ — they are the in-memory working
shape services build up before a router projects it into a response schema.
Legacy equivalent: the plain JS objects DataService.gs's
buildAllocationModel_() assembles before ValidationService.gs/Code.gs act on them.
"""

from dataclasses import dataclass, field
from datetime import date as date_
from decimal import Decimal

from rmas.models.party import Party
from rmas.services.validation_service import Totals


@dataclass
class AllocationLine:
    priority: str
    party: str
    party_key: str
    sector: str
    sector_key: str
    purity: str
    previous_requirement: Decimal
    today_required: Decimal
    alloted: Decimal
    balance: Decimal
    from_submission: bool = False
    is_finalised: bool = False


@dataclass
class FlowLine:
    sector: str
    sector_key: str
    party: str
    party_key: str
    previous_acquired: Decimal
    today_acquired: Decimal
    from_submission: bool = False
    is_finalised: bool = False


@dataclass
class StagingSubmissionSummary:
    party: str
    operator_email: str
    operator_name: str
    submitted_at: str
    submission_id: str
    total_required: Decimal
    total_acquired: Decimal
    status: str = ""


@dataclass
class AllocationModel:
    selected_date: date_
    previous_source_date: date_ | None
    rule_source_date: date_
    allocation_source_date: date_ | None
    flow_source_date: date_ | None
    used_fallback_source: bool
    has_previous_data: bool
    is_saved: bool
    saved_record_count: int
    saved_flow_record_count: int
    allocations: list[AllocationLine]
    metal_flow: list[FlowLine]
    parties: list[Party]
    totals: Totals
    total_previous_acquired: Decimal

    role: str = "ADMIN"
    is_operator: bool = False
    can_edit_required: bool = True
    can_edit_acquired: bool = True
    can_edit_alloted: bool = True
    show_global_totals: bool = True
    read_only: bool = False
    can_revise: bool = False

    is_submitted: bool = False
    submitted_at: str = ""
    submitted_by: str = ""
    staging_submissions: list[StagingSubmissionSummary] = field(default_factory=list)
