"""
models/sector.py
Royal Metal Allocation System — Python port

Two separate sets, deliberately not merged (schema.sql, "Why two sector tables
and not one"): allocation sectors carry priority and purity and represent
DEMAND; flow sectors carry neither and represent SUPPLY. A name may legitimately
appear in both — those are distinct records.

Sector names, priorities and purities are data, never code (CLAUDE.md section 6,
rule 15). `purity` is stored verbatim as TEXT ('75%', '22K', …) — never parsed
into a number.

`priority` is ALSO stored verbatim as TEXT ('Priority 1'…'Priority 6'), a
departure from schema.sql's `INTEGER` — resolved 2026-09-20. Legacy holds it as
a string and shows it to users unchanged: ReportService.gs uses it as the
filter-dropdown label (line 204), as the "by priority" dashboard grouping key
(line 587) and in text search (line 107). Storing an integer would mean
reconstructing that wording for display. The `.badge--p1`…`.badge--p6` CSS class
is derived from the label client-side, exactly as legacy's priorityClass() does
by matching the first digit.
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Sector(Base):
    """Allocation sector — legacy Metal Generator range A7:C25 plus Party."""

    __tablename__ = "sector"

    sector_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sector_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # TEXT, not INTEGER — stored exactly as the sheet writes it. See docstring.
    priority: Mapped[str] = mapped_column(String, nullable=False)
    purity: Mapped[str] = mapped_column(String, nullable=False)
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("party.party_id"), nullable=False
    )
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="ck_sector_is_active"),
        nullable=False,
        server_default=text("1"),
    )
    created_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))")
    )


class FlowSector(Base):
    """Metal Flow sector — legacy Metal Generator range I7:I14, keyed by party."""

    __tablename__ = "flow_sector"

    flow_sector_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sector_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("party.party_id"), nullable=False
    )
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="ck_flow_sector_is_active"),
        nullable=False,
        server_default=text("1"),
    )
    created_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))")
    )
