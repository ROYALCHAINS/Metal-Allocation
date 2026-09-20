"""
models/staging.py
Royal Metal Allocation System — Python port

Operator submissions awaiting an administrator's commit. Nothing here touches
the masters; only the admin save path does (CLAUDE.md section 1, two-stage
daily workflow).

Allocation and flow rows are kept in one table with a record_type
discriminator, matching legacy's RECORD_TYPE on the staging sheet, with a CHECK
ensuring exactly one of sector_id/flow_sector_id is set per row.

DEVIATION FROM THE SUPPLIED schema.sql — status vocabulary.
schema.sql has `status TEXT NOT NULL DEFAULT 'PENDING'` with no CHECK. Legacy's
STAGING_STATUS (StagingService.gs lines 37-40) has exactly two values and no
'PENDING': SUBMITTED ("waiting for the administrator") and CONSUMED ("the
administrator has saved this date"). Using 'PENDING' would put a value in the
column that no legacy code path ever produces or checks for — and
markStagingConsumed_() only ever matches rows whose status is SUBMITTED, so
'PENDING' rows would be silently skipped at commit time. The legacy vocabulary
is used here instead, with a CHECK to keep it closed.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

STAGING_STATUSES = ("SUBMITTED", "CONSUMED")
RECORD_TYPES = ("ALLOCATION", "FLOW")


class MetalRequirementStaging(Base):
    __tablename__ = "metal_requirement_staging"
    __table_args__ = (
        CheckConstraint(
            "allocation_date IS strftime('%Y-%m-%d', allocation_date)",
            name="ck_staging_date_format",
        ),
        CheckConstraint("record_type IN ('ALLOCATION', 'FLOW')", name="ck_staging_record_type"),
        CheckConstraint(
            "status IN ('SUBMITTED', 'CONSUMED')", name="ck_staging_status"
        ),
        CheckConstraint(
            "(record_type = 'ALLOCATION' AND sector_id IS NOT NULL AND flow_sector_id IS NULL)"
            " OR (record_type = 'FLOW' AND flow_sector_id IS NOT NULL AND sector_id IS NULL)",
            name="ck_staging_exactly_one_sector",
        ),
    )

    staging_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[str] = mapped_column(String, nullable=False)

    allocation_date: Mapped[str] = mapped_column(String, nullable=False, index=True)

    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("party.party_id"), nullable=False
    )
    operator_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    submitted_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))")
    )

    record_type: Mapped[str] = mapped_column(String, nullable=False)

    sector_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sector.sector_id"), nullable=True
    )
    flow_sector_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("flow_sector.flow_sector_id"), nullable=True
    )

    value_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'SUBMITTED'")
    )
