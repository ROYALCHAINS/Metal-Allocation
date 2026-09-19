"""
schemas/audit.py — administrator-only audit viewer shapes.
Legacy: AuditReportService.gs.
"""

from datetime import date as date_
from decimal import Decimal

from pydantic import BaseModel, Field


class AuditFilters(BaseModel):
    from_date: date_ | None = None
    to_date: date_ | None = None
    action_type: str = "all"
    status: str = "all"
    user: str = "all"
    limit: int = 500


class AuditFilterOptionsOut(BaseModel):
    actions: list[str]
    statuses: list[str]
    users: list[str]
    entry_count: int
    min_date: date_ | None
    max_date: date_ | None
    suggested_from: date_ | None
    suggested_to: date_ | None


class AuditLogRowOut(BaseModel):
    audit_id: str
    allocation_date_key: date_ | None
    allocation_date_display: str
    action_type: str
    revision_number: int
    user_email: str
    timestamp_display: str
    reason_preview: str
    request_id: str
    status: str
    has_snapshots: bool


class AuditCountsOut(BaseModel):
    total: int
    success: int
    blocked: int
    failed: int
    revisions: int


class AuditLogSummaryOut(BaseModel):
    record_count: int
    returned_count: int
    truncated: bool
    counts: AuditCountsOut


class AuditLogOut(BaseModel):
    rows: list[AuditLogRowOut]
    summary: AuditLogSummaryOut


class AllocationSnapshotRowOut(BaseModel):
    priority: str
    sector: str
    purity: str
    previous_requirement: Decimal
    today_required: Decimal
    alloted: Decimal
    balance: Decimal


class FlowSnapshotRowOut(BaseModel):
    sector: str
    acquired: Decimal


class AllocationDiffRowOut(BaseModel):
    sector: str
    priority: str
    before: AllocationSnapshotRowOut | None
    after: AllocationSnapshotRowOut | None
    changed: dict[str, bool]
    any_change: bool
    only_before: bool
    only_after: bool


class FlowDiffRowOut(BaseModel):
    sector: str
    before: Decimal | None
    after: Decimal | None
    changed: bool
    only_before: bool
    only_after: bool


class SnapshotTotalsOut(BaseModel):
    previous_requirement: Decimal = Decimal("0")
    today_required: Decimal = Decimal("0")
    alloted: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    acquired: Decimal = Decimal("0")
    count: int = 0


class AuditEntryTotalsOut(BaseModel):
    before_allocation: SnapshotTotalsOut
    after_allocation: SnapshotTotalsOut
    before_flow: SnapshotTotalsOut
    after_flow: SnapshotTotalsOut


class AuditEntryDetailOut(BaseModel):
    audit_id: str
    allocation_date_key: date_ | None
    allocation_date_display: str
    action_type: str
    revision_number: int
    user_email: str
    timestamp_display: str
    reason: str
    request_id: str
    status: str
    has_before: bool
    has_after: bool
    allocation_diff: list[AllocationDiffRowOut] = Field(default_factory=list)
    flow_diff: list[FlowDiffRowOut] = Field(default_factory=list)
    totals: AuditEntryTotalsOut
    changed_sectors: int
    changed_flow_sectors: int


class DateRevisionSummaryOut(BaseModel):
    allocation_date: date_
    revision_count: int
    latest_revision_number: int
    last_revised_by: str
    last_revised_at: str
    last_revision_reason: str
    originally_saved_by: str
    originally_saved_at: str
