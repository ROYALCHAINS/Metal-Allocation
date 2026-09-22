"""
repository/audit_repo.py
Royal Metal Allocation System — Python port

The append-only audit log. INSERT only — there is deliberately no update or
delete function here, and the database enforces it with triggers as well
(CLAUDE.md section 6, rule 13).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.audit import MetalAllocationAuditLog


def insert_entry(db: Session, entry: MetalAllocationAuditLog) -> MetalAllocationAuditLog:
    db.add(entry)
    db.flush()
    return entry


def get_latest_revision_number(db: Session, allocation_date: str) -> int:
    """Highest revision number already recorded for a date, 0 when never revised.

    Ports getLatestRevisionNumber_(): only SUCCESS entries count, so a failed or
    blocked revision attempt never advances the sequence.
    """
    return (
        db.scalar(
            select(func.max(MetalAllocationAuditLog.revision_number)).where(
                MetalAllocationAuditLog.allocation_date == allocation_date,
                MetalAllocationAuditLog.action_status == "SUCCESS",
            )
        )
        or 0
    )


def _apply_audit_filters(
    stmt,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    user: str | None = None,
    search: str | None = None,
):
    """The audit list's filters.

    THE DATE WINDOW DELIBERATELY SPARES UNDATED ENTRIES (page spec, rule 4).
    An entry with no allocation date is a hard failure that happened before the
    date could be resolved — exactly the thing the log exists to record — so a
    plain `date BETWEEN ...` would hide it. The NULL test is what keeps it.
    """
    date_column = MetalAllocationAuditLog.allocation_date
    undated = date_column.is_(None) | (date_column == "")
    if date_from:
        stmt = stmt.where(undated | (date_column >= date_from))
    if date_to:
        stmt = stmt.where(undated | (date_column <= date_to))

    if action_type:
        stmt = stmt.where(MetalAllocationAuditLog.action_type == action_type)
    if status:
        stmt = stmt.where(MetalAllocationAuditLog.action_status == status)
    if user:
        stmt = stmt.where(MetalAllocationAuditLog.user_email == user)

    if search:
        # Legacy searches audit ID, user, reason, request ID and action type.
        # The control was removed from the page; the parameter stays.
        like = f"%{search}%"
        stmt = stmt.where(
            MetalAllocationAuditLog.audit_id.ilike(like)
            | MetalAllocationAuditLog.user_email.ilike(like)
            | MetalAllocationAuditLog.revision_reason.ilike(like)
            | MetalAllocationAuditLog.request_id.ilike(like)
            | MetalAllocationAuditLog.action_type.ilike(like)
        )
    return stmt


def query_log(db: Session, *, limit: int, **filters) -> list[MetalAllocationAuditLog]:
    """Newest first, tie-broken by insertion order descending.

    The tie-break matters: entries written in the same second would otherwise
    come back in an arbitrary order, and audit_row_id is this port's equivalent
    of the sheet row number legacy sorts on.
    """
    stmt = (
        select(MetalAllocationAuditLog)
        .order_by(
            MetalAllocationAuditLog.action_timestamp.desc(),
            MetalAllocationAuditLog.audit_row_id.desc(),
        )
        .limit(limit)
    )
    return list(db.scalars(_apply_audit_filters(stmt, **filters)))


def count_by_status(db: Session, **filters) -> dict[str, int]:
    """Counts over the FULL matched set, before truncation, so the KPI cards
    stay accurate even when the table shows only the first 500 rows."""
    stmt = _apply_audit_filters(
        select(
            MetalAllocationAuditLog.action_status,
            MetalAllocationAuditLog.action_type,
            func.count(),
        ).group_by(
            MetalAllocationAuditLog.action_status, MetalAllocationAuditLog.action_type
        ),
        **filters,
    )

    counts = {"total": 0, "success": 0, "blocked": 0, "failed": 0, "revisions": 0}
    for status, action_type, count in db.execute(stmt):
        counts["total"] += count
        if status == "SUCCESS":
            counts["success"] += count
        elif status == "BLOCKED":
            counts["blocked"] += count
        elif status == "FAILED":
            counts["failed"] += count
        # Revisions OVERLAP the three status counts and must never be added to
        # them — a REVISE is counted at any status.
        if action_type == "REVISE":
            counts["revisions"] += count
    return counts


def distinct_filter_values(db: Session):
    """The Action / Status / User selects are built from the data, never from a
    hard-coded list, so a value legacy wrote still appears."""
    def column(attr):
        return sorted(v for (v,) in db.execute(select(attr).distinct()) if v)

    return (
        column(MetalAllocationAuditLog.action_type),
        column(MetalAllocationAuditLog.action_status),
        column(MetalAllocationAuditLog.user_email),
    )


def date_bounds(db: Session):
    """Earliest and latest allocation date present, ignoring undated entries."""
    return db.execute(
        select(
            func.min(MetalAllocationAuditLog.allocation_date),
            func.max(MetalAllocationAuditLog.allocation_date),
            func.count(),
        ).where(
            MetalAllocationAuditLog.allocation_date.is_not(None),
            MetalAllocationAuditLog.allocation_date != "",
        )
    ).one()


def total_entry_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(MetalAllocationAuditLog)) or 0


def get_entry(db: Session, audit_id: str) -> MetalAllocationAuditLog | None:
    return db.scalar(
        select(MetalAllocationAuditLog).where(MetalAllocationAuditLog.audit_id == audit_id)
    )


def get_entries_for_date(db: Session, allocation_date: str) -> list[MetalAllocationAuditLog]:
    return list(
        db.scalars(
            select(MetalAllocationAuditLog)
            .where(MetalAllocationAuditLog.allocation_date == allocation_date)
            .order_by(MetalAllocationAuditLog.action_timestamp)
        )
    )


def get_success_entries_for_date(
    db: Session, allocation_date: str
) -> list[MetalAllocationAuditLog]:
    """Every SUCCESSFUL entry for one date, oldest first.

    Ports the filter in getDateRevisionSummary() (AuditReportService.gs:523):
    date plus status SUCCESS, with the action-type partition left to the caller
    exactly as legacy does it. A failed or blocked revision attempt is invisible
    here, which is the point — it never happened.

    Deliberately not get_entries_for_date() above, which is unfiltered on status
    and would let a FAILED_REVISION inflate the count.

    The audit_row_id tie-break matters for the same reason it does in
    query_log(): action_timestamp comes from datetime('now'), which has
    one-second granularity, so without it "the first SAVE of this date" is not
    a stable answer.
    """
    return list(
        db.scalars(
            select(MetalAllocationAuditLog)
            .where(
                MetalAllocationAuditLog.allocation_date == allocation_date,
                MetalAllocationAuditLog.action_status == "SUCCESS",
            )
            .order_by(
                MetalAllocationAuditLog.action_timestamp,
                MetalAllocationAuditLog.audit_row_id,
            )
        )
    )


def get_children(db: Session, parent_audit_id: str) -> list[MetalAllocationAuditLog]:
    """The cascade entries a revision caused, oldest date first.

    Ordered by allocation_date rather than by timestamp: they are written in one
    transaction within the same second, so the timestamp cannot separate them,
    and the date is the order a reader wants anyway.
    """
    return list(
        db.scalars(
            select(MetalAllocationAuditLog)
            .where(MetalAllocationAuditLog.parent_audit_id == parent_audit_id)
            .order_by(MetalAllocationAuditLog.allocation_date)
        )
    )


def latest_row_id(db: Session) -> int:
    """The newest audit_row_id, or 0 on an empty log.

    The cursor for the notification feed. audit_row_id rather than a timestamp
    because action_timestamp has one-second granularity, so a timestamp cursor
    would either replay or skip entries written inside the same second — and a
    cascade writes several.
    """
    return db.scalar(select(func.max(MetalAllocationAuditLog.audit_row_id))) or 0


def events_after(
    db: Session,
    *,
    after: int,
    action_types: tuple[str, ...],
    exclude_email: str,
    limit: int = 20,
):
    """Successful entries newer than `after`, for the notification feed.

    Oldest first, so the caller can advance its cursor by taking the last id
    and toasts arrive in the order the events happened.

    `exclude_email` drops the caller's own actions: an operator does not need
    telling that they themselves just submitted, and the acting user already
    saw a confirmation banner.
    """
    return list(
        db.scalars(
            select(MetalAllocationAuditLog)
            .where(
                MetalAllocationAuditLog.audit_row_id > after,
                MetalAllocationAuditLog.action_status == "SUCCESS",
                MetalAllocationAuditLog.action_type.in_(action_types),
                MetalAllocationAuditLog.user_email != exclude_email,
            )
            .order_by(MetalAllocationAuditLog.audit_row_id)
            .limit(limit)
        )
    )
