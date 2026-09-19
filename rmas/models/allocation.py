"""
allocation.py — Metal Master: one immutable row per (allocation_date, sector).

Legacy: DataService.gs's Metal Master reads/writes (readMasterRows_,
buildMasterRowValues_, appendBothMasters_). Rows are appended by
saveDailyAllocation() and replaced wholesale (delete + re-insert) only by
reviseDailyAllocation() — see services/allocation_service.py.

previous_requirement and balance are SIGNED: an earlier over-allocation
carries a negative balance forward as next day's previous_requirement, which
assertSignedWeight_ only bounds in magnitude, never in sign. today_required
and alloted are validated non-negative inputs (assertValidWeight_), hence the
CHECK constraints below.
"""

from datetime import date as date_
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rmas.database import Base

WEIGHT = Numeric(12, 3, asdecimal=True)


class AllocationRecord(Base):
    __tablename__ = "allocations"
    __table_args__ = (
        UniqueConstraint("allocation_date", "sector_id", name="uq_allocation_date_sector"),
        CheckConstraint("today_required >= 0", name="ck_allocation_today_required_nonneg"),
        CheckConstraint("alloted >= 0", name="ck_allocation_alloted_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    allocation_date: Mapped[date_] = mapped_column(Date, index=True)
    sector_id: Mapped[int] = mapped_column(ForeignKey("allocation_sectors.id"))

    # Denormalized at save time, mirroring the legacy master row which froze
    # priority/purity into the row rather than re-joining Metal Generator.
    priority: Mapped[str] = mapped_column(default="")
    purity: Mapped[str] = mapped_column(default="Any")

    previous_requirement: Mapped[Decimal] = mapped_column(WEIGHT)  # signed
    today_required: Mapped[Decimal] = mapped_column(WEIGHT)
    alloted: Mapped[Decimal] = mapped_column(WEIGHT)
    balance: Mapped[Decimal] = mapped_column(WEIGHT)  # signed

    sector = relationship("AllocationSector")
