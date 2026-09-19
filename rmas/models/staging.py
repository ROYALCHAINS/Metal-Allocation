"""
staging.py — operator submissions, staged before an administrator's save.

Legacy: StagingService.gs's "Metal Requirement Staging" sheet. Keeps
ALLOCATION and FLOW record types separate (CLAUDE.md 6.17) since they are
different sector sets with different sector counts. A submission is one-shot
per (allocation_date, party): see services/staging_service.py for the lock
that enforces this — it is not a DB constraint, because CONSUMED rows for the
same date/party legitimately coexist with the historical SUBMITTED ones.
"""

import enum
from datetime import date as date_, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Date, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rmas.database import Base


class RecordType(str, enum.Enum):
    ALLOCATION = "ALLOCATION"
    FLOW = "FLOW"


class StagingStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"  # waiting for the administrator
    CONSUMED = "CONSUMED"    # the administrator has saved this date


class StagingRequirement(Base):
    __tablename__ = "staging_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(80), index=True)
    allocation_date: Mapped[date_] = mapped_column(Date, index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"))
    operator_email: Mapped[str] = mapped_column(String(320))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    record_type: Mapped[RecordType] = mapped_column(Enum(RecordType, native_enum=False, length=20))
    sector_key: Mapped[str] = mapped_column(String(200))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 3, asdecimal=True))
    status: Mapped[StagingStatus] = mapped_column(
        Enum(StagingStatus, native_enum=False, length=20), default=StagingStatus.SUBMITTED
    )

    party = relationship("Party")
