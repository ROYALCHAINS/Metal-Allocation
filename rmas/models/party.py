"""
party.py — Metal Generator's distinct parties.

Legacy: DataService.gs's readPartyDefinitions_() (derived, not a table of its
own, in the sheet-based system). Here it is a first-class table because
CLAUDE.md 6.15 requires party names to be data, not code, and both sector
tables reference it by foreign key.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from rmas.database import Base


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(primary_key=True)
    party_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    party_name: Mapped[str] = mapped_column(String(200))
