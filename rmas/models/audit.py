"""
models/audit.py
Royal Metal Allocation System — Python port

Append-only audit log. No UPDATE, no DELETE, ever — enforced by database
triggers (see the migration), not merely by convention (CLAUDE.md section 6,
rule 13). Failed and blocked attempts are logged too, not just successes
(rule 14).

DEVIATION FROM THE SUPPLIED schema.sql — action_type CHECK list.
schema.sql allows only the six AUDIT_ACTIONS from AuditService.gs. Legacy also
writes three more to the same log, resolved lazily by StagingService.gs's
stagingAuditAction_(): SUBMIT_REQUIREMENT, BLOCKED_RESUBMISSION and
FAILED_SUBMISSION (StagingService.gs lines 28-33, 471, 509, 541). With the
narrower list, every operator-submission audit write would be rejected by the
CHECK at runtime once staging is ported. All nine legacy values are allowed
here. This restores legacy fidelity rather than inventing anything — but it is
a deliberate departure from the supplied DDL, so it is called out here.
"""

from sqlalchemy import CheckConstraint, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

# The complete set legacy actually writes: six from AuditService.gs's
# AUDIT_ACTIONS plus three from StagingService.gs's stagingAuditAction_().
AUDIT_ACTION_TYPES = (
    "SAVE",
    "REVISE",
    "BLOCKED_DUPLICATE",
    "FAILED_SAVE",
    "FAILED_REVISION",
    "UNAUTHORIZED_REVISION",
    "SUBMIT_REQUIREMENT",
    "BLOCKED_RESUBMISSION",
    "FAILED_SUBMISSION",
    # A later date whose previous_requirement and balance were recomputed as a
    # CONSEQUENCE of revising an earlier date. Not an administrator edit, which
    # is why it is a separate value: the Revisions KPI counts REVISE alone.
    "RECALCULATE",
)

AUDIT_STATUSES = ("SUCCESS", "BLOCKED", "FAILED")

_ACTION_LIST = ", ".join(f"'{value}'" for value in AUDIT_ACTION_TYPES)
_STATUS_LIST = ", ".join(f"'{value}'" for value in AUDIT_STATUSES)


class MetalAllocationAuditLog(Base):
    __tablename__ = "metal_allocation_audit_log"
    __table_args__ = (
        CheckConstraint(
            "allocation_date IS NULL OR "
            "allocation_date IS strftime('%Y-%m-%d', allocation_date)",
            name="ck_audit_date_format",
        ),
        CheckConstraint(f"action_type IN ({_ACTION_LIST})", name="ck_audit_action_type"),
        CheckConstraint(f"action_status IN ({_STATUS_LIST})", name="ck_audit_action_status"),
    )

    audit_row_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    # NULLABLE (migration 0004). A hard failure can be recorded before the
    # allocation date was ever resolved, and the Audit Log must show it rather
    # than refuse to store it — see the page spec's rule 4. The date window in
    # audit_repo deliberately spares undated entries.
    allocation_date: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_status: Mapped[str] = mapped_column(String, nullable=False)

    revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    user_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_timestamp: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))"), index=True
    )
    revision_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    # Full before/after state as JSON, kept verbatim so a revision can be
    # diffed or replayed long after the sector definitions have changed.
    previous_allocation_data: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_allocation_data: Mapped[str | None] = mapped_column(String, nullable=True)
    previous_metal_flow_data: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_metal_flow_data: Mapped[str | None] = mapped_column(String, nullable=True)

    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # The REVISE entry that caused this RECALCULATE entry. NULL on every other
    # row. A DEPARTURE from schema.sql, which predates the forward cascade.
    #
    # Deliberately NOT a foreign key, matching request_id above. Nothing in this
    # application turns on PRAGMA foreign_keys, so a self-FK would be
    # declarative only — and would quietly start being enforced the day someone
    # enabled it, on a table whose triggers forbid deleting anything anyway.
    parent_audit_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
