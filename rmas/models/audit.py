"""
audit.py — the append-only audit log.

Legacy: AuditService.gs's writer + AuditReportService.gs's reader, backing
the "Metal Allocation Audit Log" sheet. APPEND-ONLY: no service or router may
issue an UPDATE or DELETE against this table, ever (CLAUDE.md 6.13).

user_email is stored as plain text, not a foreign key to users.id, so the
audit trail survives a user being removed or renamed later — exactly as the
legacy sheet recorded a plain email string per row.

Snapshots are stored as JSON, matching the legacy compact JSON strings
({p,s,pu,pr,tr,al,bl} per allocation row, {s,ac} per flow row) — decoding and
diffing them is services/audit_service.py's job, not this model's.
"""

from datetime import date as date_, datetime

from sqlalchemy import JSON, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from rmas.database import Base


class AuditLogEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)

    # Nullable: a hard failure before the date was even resolved must still be
    # logged (CLAUDE.md 6.14), so this cannot be NOT NULL.
    allocation_date: Mapped[date_ | None] = mapped_column(Date, nullable=True, index=True)

    # Free-text, not a DB enum: the legacy system defines audit actions in two
    # places (AuditService.gs's six core actions plus StagingService.gs's
    # three submission actions) and a future workflow may add more without a
    # migration. services/audit_service.py owns the canonical list of values.
    action_type: Mapped[str] = mapped_column(String(40), index=True)

    revision_number: Mapped[int] = mapped_column(Integer, default=0)
    user_email: Mapped[str] = mapped_column(String(320))
    action_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")

    previous_allocation_data: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_allocation_data: Mapped[list | None] = mapped_column(JSON, nullable=True)
    previous_flow_data: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_flow_data: Mapped[list | None] = mapped_column(JSON, nullable=True)

    request_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    action_status: Mapped[str] = mapped_column(String(20))  # SUCCESS | BLOCKED | FAILED
