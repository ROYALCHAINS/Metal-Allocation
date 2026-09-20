"""
models/party.py
Royal Metal Allocation System — Python port

Parties own sectors. In legacy there was no party list: readPartyDefinitions_()
derived the distinct party set by scanning the Party column of the allocation
and flow sector rows. Here it is a real table, so a party can be referenced by
id and scope can be a foreign key rather than a string match.

`party_key` is the normalised form produced by validation_service.normalize_key,
mirroring legacy's normalizePartyKey_() — which was a direct alias of
normalizeSectorKey_(), so parties and sectors share one rule.

BE PRECISE ABOUT WHAT THAT RULE DOES. It lowercases, trims, collapses RUNS of
whitespace, and unifies dash characters (en dash, em dash, minus) to a hyphen.
It does NOT remove single spaces and does NOT strip punctuation:

    'Royal Chain'   -> 'royal chain'
    'royal  chain'  -> 'royal chain'
    'RoyalChain'    -> 'royalchain'    <- does NOT match the first two
    'Royal-Chain'   -> 'royal-chain'   <- nor does this

Legacy's Config.gs comments claim matching happens "ignoring spacing and dash
style"; that overstates it, and believing it would lead you to expect
'RoyalChain' to resolve. Spelling must be consistent between the seed data and
the scope assignments. See SECTORS_EXPLAINED.md section 3.
"""

from sqlalchemy import Boolean, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Party(Base):
    __tablename__ = "party"

    party_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    party_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="ck_party_is_active"),
        nullable=False,
        server_default=text("1"),
    )
    created_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))")
    )
