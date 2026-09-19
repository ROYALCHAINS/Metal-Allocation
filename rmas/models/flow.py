"""
flow.py — Metal Flow Master: one immutable row per (flow_date, flow_sector).

Legacy: DataService.gs's Metal Flow Master reads/writes
(readFlowMasterRows_, buildFlowRowValues_). acquired is a validated
non-negative input (assertValidWeight_).
"""

from datetime import date as date_
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rmas.database import Base

WEIGHT = Numeric(12, 3, asdecimal=True)


class FlowRecord(Base):
    __tablename__ = "metal_flow"
    __table_args__ = (
        UniqueConstraint("flow_date", "flow_sector_id", name="uq_flow_date_sector"),
        CheckConstraint("acquired >= 0", name="ck_flow_acquired_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    flow_date: Mapped[date_] = mapped_column(Date, index=True)
    flow_sector_id: Mapped[int] = mapped_column(ForeignKey("flow_sectors.id"))
    acquired: Mapped[Decimal] = mapped_column(WEIGHT)

    flow_sector = relationship("FlowSector")
