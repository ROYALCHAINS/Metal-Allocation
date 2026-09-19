"""
sector.py — Allocation and Metal Flow sector definitions.

Legacy: DataService.gs's readAllocationSectorDefinitions_() /
readFlowSectorDefinitions_(), sourced from Metal Generator via
SchemaService.gs's header detection. SchemaService.gs itself is dropped
(CLAUDE.md 6.16) — an explicit schema replaces label-matching.

Sector names, priorities and purities are DATA, never hard-coded elsewhere
(CLAUDE.md 6.15). Nothing is seeded by this port; seeding happens once real
Metal Generator data is confirmed.
"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rmas.database import Base


class AllocationSector(Base):
    __tablename__ = "allocation_sectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    sector_name: Mapped[str] = mapped_column(String(200))
    priority: Mapped[str] = mapped_column(String(50), default="")
    # Legacy default was 'Any' when the Purity cell was blank.
    purity: Mapped[str] = mapped_column(String(100), default="Any")
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)

    party = relationship("Party")


class FlowSector(Base):
    __tablename__ = "flow_sectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    sector_name: Mapped[str] = mapped_column(String(200))
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)

    party = relationship("Party")
