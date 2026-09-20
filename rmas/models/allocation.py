"""
models/allocation.py
Royal Metal Allocation System — Python port

The allocation ledger (legacy "Metal Master"). DEMAND side.

WEIGHTS ARE INTEGER GRAMS, never float, never REAL (schema.sql design note).
The legacy system worked in kilograms to exactly 3 decimals, and 3 decimals of a
kilogram is precisely 1 gram, so integer grams is a lossless representation with
no floating-point drift. The `_g` suffix makes the unit impossible to mistake.
Convert at the application boundary via services/weight_service.py.

`priority_snapshot`/`purity_snapshot` are deliberately denormalised: the sheet
carried them on every row, and keeping them means a historical row still reports
the priority and purity that applied ON THAT DATE, even after the sector
definition is later edited.

Both snapshots are TEXT. `priority_snapshot` is a departure from schema.sql's
`INTEGER`, kept consistent with `sector.priority` — see models/sector.py.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MetalMaster(Base):
    __tablename__ = "metal_master"
    __table_args__ = (
        # One row per sector per date. A revision REPLACES the date's rows,
        # exactly as legacy's deleteRowsForDate_() + appendBothMasters_() did.
        UniqueConstraint("allocation_date", "sector_id", name="uq_master_date_sector"),
        CheckConstraint(
            "allocation_date IS strftime('%Y-%m-%d', allocation_date)",
            name="ck_master_date_format",
        ),
    )

    allocation_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    allocation_date: Mapped[str] = mapped_column(String, nullable=False, index=True)

    sector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sector.sector_id"), nullable=False
    )
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("party.party_id"), nullable=False
    )

    priority_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    purity_snapshot: Mapped[str] = mapped_column(String, nullable=False)

    previous_requirement_g: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    today_required_g: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    alloted_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    balance_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    saved_by: Mapped[str] = mapped_column(String, nullable=False)
    saved_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))")
    )
