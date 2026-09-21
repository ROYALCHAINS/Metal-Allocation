"""
services/audit_report_service.py
Royal Metal Allocation System — Python port of AuditReportService.gs

The READ side of the audit log. Writing lives in services/audit_service.py, and
the two are deliberately separate: this module only ever decodes and compares.
There is no update path and no delete path here, at any layer (rule 3).

Snapshots are stored with legacy's abbreviated keys to keep the column small —
`p` priority, `s` sector, `pu` purity, `pr` previousRequirement, `tr`
todayRequired, `al` alloted, `bl` balance, `ac` acquired — and their values are
exact kilogram STRINGS. They are decoded to integer grams here so every
comparison downstream is integer arithmetic.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from repository import audit_repo
from services.audit_service import ACTION_REVISE, ACTION_SAVE
from services.validation_service import nearly_equal_g, normalize_key
from services.weight_service import kg_to_grams

logger = logging.getLogger(__name__)

_WHITESPACE_RUN = re.compile(r"\s+")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# From legacy's AUDIT_REPORT_CONFIG.
MAX_ROWS_RETURNED = 500
DEFAULT_RANGE_DAYS = 90
MAX_REASON_PREVIEW = 140

# The four allocation fields a revision can change, in display order.
ALLOCATION_FIELDS = ("previous_requirement", "today_required", "alloted", "balance")

_ALLOCATION_KEYS = {
    "previous_requirement": "pr",
    "today_required": "tr",
    "alloted": "al",
    "balance": "bl",
}


@dataclass
class SnapshotRow:
    """One sector's state at a point in time, in integer grams."""

    sector_name: str
    sector_key: str
    priority: str = ""
    purity: str = ""
    values_g: dict[str, int] = field(default_factory=dict)


def _grams(raw) -> int:
    """A snapshot value to integer grams. Unparseable reads as zero.

    A snapshot is a historical record, not user input — it is far better to
    show a row with a zero than to refuse to render a compliance record
    because one cell was written by an older build.
    """
    if raw is None or raw == "":
        return 0
    try:
        return kg_to_grams(str(raw))
    except Exception:  # noqa: BLE001 — a bad cell must not break the request
        logger.warning("audit snapshot: unparseable weight %r", raw)
        return 0


def _load(text: str | None) -> list:
    """Decode a snapshot column, degrading to empty rather than failing.

    Rule 12: a malformed snapshot must degrade to an empty diff, never break
    the request. The entry itself is still worth showing — often it is the
    failure record that matters most.
    """
    if not text:
        return []
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        logger.warning("audit snapshot: could not decode JSON, treating as empty")
        return []
    return data if isinstance(data, list) else []


def decode_allocation_snapshot(text: str | None) -> list[SnapshotRow]:
    rows = []
    for item in _load(text):
        if not isinstance(item, dict):
            continue
        name = str(item.get("s") or "")
        rows.append(
            SnapshotRow(
                sector_name=name,
                sector_key=normalize_key(name),
                priority=str(item.get("p") or ""),
                purity=str(item.get("pu") or ""),
                values_g={
                    field_name: _grams(item.get(short))
                    for field_name, short in _ALLOCATION_KEYS.items()
                },
            )
        )
    return rows


def decode_flow_snapshot(text: str | None) -> list[SnapshotRow]:
    rows = []
    for item in _load(text):
        if not isinstance(item, dict):
            continue
        name = str(item.get("s") or "")
        rows.append(
            SnapshotRow(
                sector_name=name,
                sector_key=normalize_key(name),
                values_g={"acquired": _grams(item.get("ac"))},
            )
        )
    return rows


@dataclass
class DiffEntry:
    sector_name: str
    before: SnapshotRow | None
    after: SnapshotRow | None
    # Per-field change flags. Flow carries the single key "acquired".
    changed: dict[str, bool] = field(default_factory=dict)
    any_change: bool = False
    only_before: bool = False  # present before, gone after — sector removed
    only_after: bool = False  # absent before, present after — sector added


def _union(before: list[SnapshotRow], after: list[SnapshotRow]):
    """Union the two sector sets, keyed on the normalised name.

    First-seen order, before rows first, so a revision reads top-to-bottom in
    the order the original save had — added sectors fall to the bottom where
    they are noticeable.
    """
    order: list[str] = []
    display: dict[str, str] = {}
    before_by_key: dict[str, SnapshotRow] = {}
    after_by_key: dict[str, SnapshotRow] = {}

    for source in (before, after):
        for row in source:
            if row.sector_key not in display:
                order.append(row.sector_key)
                # The name shown is the FIRST one seen for this key, matching
                # legacy. Within one snapshot a duplicated key collapses to a
                # single entry whose values come from the LAST row but whose
                # label comes from the first.
                display[row.sector_key] = row.sector_name
            (before_by_key if source is before else after_by_key)[row.sector_key] = row

    return order, display, before_by_key, after_by_key


def _diff(before: list[SnapshotRow], after: list[SnapshotRow], fields) -> list[DiffEntry]:
    """Compare two snapshots field by field.

    Comparison is nearly_equal_g, never ==: two weights differing only by
    representation noise are not a change (rule 6).

    WHEN A SECTOR EXISTS ON ONLY ONE SIDE, EVERY FIELD COUNTS AS CHANGED. That
    is deliberate — an added or removed sector is a change in all its values,
    and marking only the non-zero ones would understate it.
    """
    order, display, before_by_key, after_by_key = _union(before, after)
    entries = []

    for key in order:
        before_row = before_by_key.get(key)
        after_row = after_by_key.get(key)
        only_before = after_row is None
        only_after = before_row is None

        if only_before or only_after:
            changed = {name: True for name in fields}
        else:
            changed = {
                name: not nearly_equal_g(
                    before_row.values_g.get(name, 0), after_row.values_g.get(name, 0)
                )
                for name in fields
            }

        entries.append(
            DiffEntry(
                sector_name=display[key],
                before=before_row,
                after=after_row,
                changed=changed,
                any_change=any(changed.values()),
                only_before=only_before,
                only_after=only_after,
            )
        )
    return entries


def diff_allocation_snapshots(before, after) -> list[DiffEntry]:
    return _diff(before, after, ALLOCATION_FIELDS)


def diff_flow_snapshots(before, after) -> list[DiffEntry]:
    return _diff(before, after, ("acquired",))


def snapshot_totals(rows: list[SnapshotRow], fields) -> dict[str, int]:
    """Column sums, plus the row count so a change in row count is visible."""
    totals = {name: sum(row.values_g.get(name, 0) for row in rows) for name in fields}
    totals["row_count"] = len(rows)
    return totals


def allocation_totals(rows: list[SnapshotRow]) -> dict[str, int]:
    return snapshot_totals(rows, ALLOCATION_FIELDS)


def flow_totals(rows: list[SnapshotRow]) -> dict[str, int]:
    return snapshot_totals(rows, ("acquired",))


def preview_reason(reason: str | None) -> str:
    """Ports previewReason_(). The list carries the preview only — the full
    text comes from the detail fetch, because a list can hold 500 rows.

    Whitespace runs collapse first, so a reason typed across several lines does
    not blow the table row open.
    """
    text = _WHITESPACE_RUN.sub(" ", reason or "").strip()
    if len(text) <= MAX_REASON_PREVIEW:
        return text
    # 139 characters plus the ellipsis — exactly MAX_REASON_PREVIEW.
    return text[: MAX_REASON_PREVIEW - 1] + "…"


def format_audit_timestamp(stored: str | None) -> str:
    """Ports formatAuditTimestamp_(): 'dd-MMM-yyyy HH:mm:ss'.

    The month abbreviation is spelled out from a fixed table rather than
    strftime('%b'), which follows the machine locale and would render a
    compliance record differently on a differently-configured server.

    NOTE: the stored value comes from SQLite's datetime('now'), which is UTC,
    while the application timezone is Asia/Kolkata. That gap is pre-existing
    and is flagged rather than silently corrected here — fixing it means
    changing how the column is written, not how it is displayed.
    """
    text = (stored or "").strip()
    if not text:
        return ""
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return (
        f"{stamp.day:02d}-{_MONTHS[stamp.month - 1]}-{stamp.year} "
        f"{stamp.hour:02d}:{stamp.minute:02d}:{stamp.second:02d}"
    )


# ------------------------------------------------- date revision summary


@dataclass(frozen=True)
class DateRevisionSummary:
    """Who committed one allocation date, and whether it has changed since.

    Timestamps are the RAW stored values; the router formats them, the same
    division of labour already used for SubmissionSummary.submitted_at.
    """

    revision_count: int
    latest_revision_number: int
    last_revised_by: str | None
    last_revised_at: str | None
    last_revision_reason: str | None
    originally_saved_by: str | None
    originally_saved_at: str | None
    message: str


def get_date_revision_summary(db: Session, allocation_date: str) -> DateRevisionSummary:
    """Ports getDateRevisionSummary() (AuditReportService.gs:517).

    NOT ADMINISTRATOR-ONLY, and that is deliberate. This is the one function in
    AuditReportService.gs that does not call assertAuditAccess_(); its docstring
    says why — "Safe for every user: returns counts and timestamps only, never
    snapshots". The caller must preserve that: see routers/allocations.py.

    A note on what the two counts mean. `revision_count` is how many successful
    revisions the date has had; `latest_revision_number` is the number carried
    by the newest of them. Legacy reads the latter off that row rather than
    taking MAX(revision_number) over the date, so a SAVE carrying a non-zero
    revision number could never inflate it. Do not "simplify" this to
    audit_repo.get_latest_revision_number() — it answers a different question.
    """
    rows = audit_repo.get_success_entries_for_date(db, allocation_date)
    revisions = [row for row in rows if row.action_type == ACTION_REVISE]
    saves = [row for row in rows if row.action_type == ACTION_SAVE]

    # Rows arrive oldest-first, so the newest revision is last and the ORIGINAL
    # save is first. Legacy sorts its two lists in opposite directions for
    # exactly this reason (AuditReportService.gs:529-534): "originally saved by"
    # is the FIRST save of the date, never the most recent one.
    latest = revisions[-1] if revisions else None
    original = saves[0] if saves else None

    # A staging submission is neither a save nor a revision; it drops out of
    # both partitions here, as it does in legacy.
    return DateRevisionSummary(
        revision_count=len(revisions),
        latest_revision_number=latest.revision_number if latest else 0,
        last_revised_by=latest.user_email if latest else None,
        last_revised_at=latest.action_timestamp if latest else None,
        # The FULL reason, never preview_reason() — legacy returns it whole.
        last_revision_reason=latest.revision_reason if latest else None,
        originally_saved_by=original.user_email if original else None,
        originally_saved_at=original.action_timestamp if original else None,
        message=(
            f"This date has been revised {len(revisions)} time(s)."
            if revisions
            else "This date has not been revised."
        ),
    )
