"""
models/flow.py
Royal Metal Allocation System — Python port

The supply ledger (legacy "Metal Flow Master"). Metal arriving, per date, per
flow sector. Weights are INTEGER GRAMS — see models/allocation.py's docstring.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MetalFlowMaster(Base):
    __tablename__ = "metal_flow_master"
    __table_args__ = (
        UniqueConstraint("allocation_date", "flow_sector_id", name="uq_flow_date_sector"),
        CheckConstraint(
            "allocation_date IS strftime('%Y-%m-%d', allocation_date)",
            name="ck_flow_date_format",
        ),
        CheckConstraint("acquired_g >= 0", name="ck_flow_acquired_non_negative"),
    )

    flow_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    allocation_date: Mapped[str] = mapped_column(String, nullable=False, index=True)

    flow_sector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("flow_sector.flow_sector_id"), nullable=False
    )
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("party.party_id"), nullable=False
    )

    acquired_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    saved_by: Mapped[str] = mapped_column(String, nullable=False)
    saved_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))")
    )
