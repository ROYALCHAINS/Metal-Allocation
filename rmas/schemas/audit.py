"""schemas/audit.py — the administrator-only audit viewer.

Never expose another account's scope or the administrator list (rule 10); these
responses carry only what the log itself records.

Snapshots are NOT in the list payload. They load on demand from the detail
endpoint (page spec, rule 8) — a list can carry 500 rows and each snapshot is
the full state of every sector.
"""

from decimal import Decimal

from pydantic import BaseModel


class AuditFilterOptions(BaseModel):
    """Built from the data, never a hard-coded list."""

    actions: list[str]
    statuses: list[str]
    users: list[str]
    entry_count: int
    min_date: str | None
    max_date: str | None
    # A 90-day window counted back from the LATEST allocation date in the log,
    # not from today, and clamped so it never precedes the earliest entry.
    suggested_from: str
    suggested_to: str


class AuditEntryRow(BaseModel):
    audit_id: str
    # Nullable: a hard failure can be recorded before the date was resolved.
    allocation_date: str | None
    allocation_date_display: str | None
    action_type: str
    action_status: str
    revision_number: int
    user_email: str
    timestamp_display: str
    # Truncated to 140 characters server-side; the modal fetches the full text.
    reason_preview: str
    request_id: str | None
    has_snapshots: bool


class AuditCounts(BaseModel):
    """Counts, not weights — plain integers.

    total/success/blocked/failed are mutually exclusive and sum to total.
    `revisions` OVERLAPS them and must not be added in.
    """

    total: int
    success: int
    blocked: int
    failed: int
    revisions: int


class AuditLogSummary(BaseModel):
    record_count: int
    returned_count: int
    truncated: bool
    counts: AuditCounts


class AuditLogResponse(BaseModel):
    rows: list[AuditEntryRow]
    summary: AuditLogSummary


class DiffSide(BaseModel):
    """One sector's state on one side of a revision, or absent entirely.

    A field that is None renders as an em-dash, never as 0.000 — absence and
    zero are different facts (rule 7).
    """

    sector_name: str
    priority: str | None = None
    purity: str | None = None
    previous_requirement_kg: Decimal | None = None
    today_required_kg: Decimal | None = None
    alloted_kg: Decimal | None = None
    balance_kg: Decimal | None = None
    acquired_kg: Decimal | None = None


class DiffRow(BaseModel):
    sector_name: str
    before: DiffSide | None
    after: DiffSide | None
    # Per-field flags. Allocation carries four keys, flow carries "acquired".
    changed: dict[str, bool]
    any_change: bool
    only_before: bool  # sector removed
    only_after: bool  # sector added


class DiffTotals(BaseModel):
    row_count: int
    previous_requirement_kg: Decimal | None = None
    today_required_kg: Decimal | None = None
    alloted_kg: Decimal | None = None
    balance_kg: Decimal | None = None
    acquired_kg: Decimal | None = None


class AuditEntryDetail(BaseModel):
    audit_id: str
    allocation_date: str | None
    allocation_date_display: str | None
    action_type: str
    action_status: str
    revision_number: int
    user_email: str
    timestamp_display: str
    # The FULL reason here, not the list's 140-character preview.
    reason: str | None
    request_id: str | None

    has_before: bool
    has_after: bool
    allocation_diff: list[DiffRow]
    flow_diff: list[DiffRow]
    before_allocation_totals: DiffTotals
    after_allocation_totals: DiffTotals
    before_flow_totals: DiffTotals
    after_flow_totals: DiffTotals
    changed_sectors: int
    changed_flow_sectors: int


class DateRevisionSummaryResponse(BaseModel):
    """One allocation date's commit history, for the Daily Allocation screen.

    NOT ADMINISTRATOR-ONLY, unlike everything else in this module. It rides on
    the allocation response rather than living under /audit precisely so that
    it keeps legacy's contract: getDateRevisionSummary() is the one function in
    AuditReportService.gs that deliberately skips assertAuditAccess_(), because
    it returns counts, names and timestamps only — never a snapshot.
    """

    revision_count: int
    # The number carried by the NEWEST revision, not MAX() over the date.
    latest_revision_number: int
    last_revised_by: str | None
    last_revised_at_display: str | None
    # Full text, never the 140-character preview the audit list uses.
    last_revision_reason: str | None
    # The FIRST save of this date, not the most recent one.
    originally_saved_by: str | None
    originally_saved_at_display: str | None
    # Legacy's own badge text, composed server-side and shown verbatim.
    message: str
