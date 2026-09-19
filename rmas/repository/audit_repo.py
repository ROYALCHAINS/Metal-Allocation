"""
audit_repo.py — the append-only audit log. INSERT and SELECT only.

CLAUDE.md 6.13: no UPDATE, no DELETE, no exceptions. This module
deliberately exposes no such function — if a future change needs one, that
is itself a sign the append-only rule is being violated, not a gap to fill.

Legacy: AuditService.gs's writeAuditEntry_() / getLatestRevisionNumber_(),
and AuditReportService.gs's readAuditRows_() (the read side).
"""

from datetime import date as date_

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rmas.models.audit import AuditLogEntry


def insert_entry(db: Session, entry: AuditLogEntry) -> str:
    """Legacy writeAuditEntry_(). Auditing must never block a business
    operation — callers are expected to catch and log, never propagate, a
    failure here, exactly as the legacy try/catch swallows write errors."""
    db.add(entry)
    db.flush()
    return entry.audit_id


def latest_revision_number(db: Session, allocation_date: date_) -> int:
    """Legacy getLatestRevisionNumber_() — highest SUCCESSful revision for a date."""
    result = db.scalar(
        select(func.max(AuditLogEntry.revision_number)).where(
            AuditLogEntry.allocation_date == allocation_date,
            AuditLogEntry.action_status == "SUCCESS",
        )
    )
    return result or 0


def get_by_audit_id(db: Session, audit_id: str) -> AuditLogEntry | None:
    return db.scalar(select(AuditLogEntry).where(AuditLogEntry.audit_id == audit_id))


def list_all(db: Session) -> list[AuditLogEntry]:
    """Legacy readAuditRows_(). Filtering/pagination is services/audit_service.py's job."""
    return list(db.scalars(select(AuditLogEntry).order_by(AuditLogEntry.action_timestamp.desc())))


def list_success_for_date(db: Session, allocation_date: date_) -> list[AuditLogEntry]:
    """Legacy getDateRevisionSummary()'s row fetch."""
    return list(
        db.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.allocation_date == allocation_date,
                AuditLogEntry.action_status == "SUCCESS",
            )
        )
    )
