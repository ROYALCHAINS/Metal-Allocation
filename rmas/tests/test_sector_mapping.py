"""tests/test_sector_mapping.py — how the two sector sets relate.

Pins the structure described in SECTORS_EXPLAINED.md, which is otherwise only
prose. Three things it asserts, all of which are easy to break by accident:

  * The two sets are SEPARATE. A name in both is two distinct records — one
    demand, one supply — and nothing joins them by name.
  * They connect through PARTY, one-to-many: one flow sector names a party, and
    that party owns many allocation sectors. There is no sector-to-sector
    mapping table anywhere, by design.
  * Keys normalise by one shared rule that unifies dash STYLE and collapses
    whitespace RUNS, but does not remove single spaces or punctuation.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models.party import Party
from models.sector import FlowSector, Sector
from services.validation_service import normalize_key


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    royal = Party(party_name="Royal Chain", party_key=normalize_key("Royal Chain"))
    factory = Party(party_name="Factory", party_key=normalize_key("Factory"))
    session.add_all([royal, factory])
    session.flush()

    # Royal Chain owns two allocation sectors; Factory owns one.
    for order, (name, party) in enumerate(
        [("RC Customer Orders", royal), ("RC Stock Orders", royal), ("Fac Orders", factory)],
        start=1,
    ):
        session.add(
            Sector(
                sector_name=name,
                sector_key=normalize_key(name),
                priority=f"Priority {order}",
                purity="Any",
                party_id=party.party_id,
                display_order=order,
            )
        )
    # One flow sector shares a name with an allocation sector, as the seed data
    # genuinely does — they are still separate records.
    session.add(
        FlowSector(
            sector_name="RC Customer Orders",
            sector_key=normalize_key("RC Customer Orders"),
            party_id=royal.party_id,
            display_order=1,
        )
    )
    session.flush()
    yield session
    session.close()


# --------------------------------------------------------- the two sets differ


def test_a_shared_name_is_two_distinct_records(db_session) -> None:
    """The same label in both tables is one demand row and one supply row, not
    one thing seen twice. Nothing in the schema ties them together."""
    name = "RC Customer Orders"
    allocation = db_session.scalar(select(Sector).where(Sector.sector_name == name))
    flow = db_session.scalar(select(FlowSector).where(FlowSector.sector_name == name))

    assert allocation is not None and flow is not None

    # No foreign key between them in either direction — nothing to join on but
    # the party they each point at.
    assert not hasattr(allocation, "flow_sector_id")
    assert not hasattr(flow, "sector_id")
    assert {fk.column.table.name for fk in Sector.__table__.foreign_keys} == {"party"}
    assert {fk.column.table.name for fk in FlowSector.__table__.foreign_keys} == {"party"}

    # The two id sequences are independent, so the ids can even collide. That
    # is precisely why an id is only meaningful alongside its table — the
    # dashboard's cross-ledger filter matches on the normalised NAME for this
    # reason, never on the id the browser sent.
    allocation.party_id = db_session.scalar(
        select(Party.party_id).where(Party.party_name == "Factory")
    )
    db_session.flush()
    db_session.refresh(flow)
    assert flow.party_id != allocation.party_id, "moving one must not move the other"


def test_only_allocation_sectors_carry_priority_and_purity(db_session) -> None:
    """Demand is prioritised and has a purity; supply is neither. This is why
    merging the tables would force both columns nullable."""
    assert hasattr(Sector, "priority") and hasattr(Sector, "purity")
    assert not hasattr(FlowSector, "priority")
    assert not hasattr(FlowSector, "purity")


# ------------------------------------------------- they connect through party


def test_one_flow_sector_reaches_many_allocation_sectors_via_its_party(
    db_session,
) -> None:
    """The whole relationship, in one query: metal acquired under a flow sector
    is the supply pool for every allocation sector owned by that same party."""
    flow = db_session.scalar(select(FlowSector))
    owned = db_session.scalars(
        select(Sector.sector_name).where(Sector.party_id == flow.party_id)
    ).all()

    assert sorted(owned) == ["RC Customer Orders", "RC Stock Orders"]
    # One-to-many: the flow sector's own name matches only one of them, and
    # that coincidence is not what makes the link.
    assert len(owned) > 1


def test_a_sector_cannot_exist_without_a_party(db_session) -> None:
    """Party is the only join between demand and supply, so it is mandatory on
    both sides — an unowned sector would be unreachable by any scope."""
    assert Sector.__table__.c.party_id.nullable is False
    assert FlowSector.__table__.c.party_id.nullable is False


def test_changing_a_sector_party_moves_it_between_pools(db_session) -> None:
    """The mapping is expressed entirely by the party column — it is data, not
    code, so re-parenting a sector needs no code change."""
    factory = db_session.scalar(select(Party).where(Party.party_name == "Factory"))
    sector = db_session.scalar(
        select(Sector).where(Sector.sector_name == "RC Stock Orders")
    )
    sector.party_id = factory.party_id
    db_session.flush()

    royal = db_session.scalar(select(Party).where(Party.party_name == "Royal Chain"))
    still_royal = db_session.scalars(
        select(Sector.sector_name).where(Sector.party_id == royal.party_id)
    ).all()
    assert still_royal == ["RC Customer Orders"]


# ----------------------------------------------------------- key normalisation


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Royal Chain", "royal chain"),
        ("  Royal Chain  ", "royal chain"),
        ("royal  chain", "royal chain"),  # whitespace RUNS collapse
        ("Royal\tChain", "royal chain"),
        ("ROYAL CHAIN", "royal chain"),
        ("RoyalChain", "royalchain"),  # a removed space does NOT collapse
        ("Royal–Chain", "royal-chain"),  # en dash  -> hyphen
        ("Royal—Chain", "royal-chain"),  # em dash  -> hyphen
        ("Royal−Chain", "royal-chain"),  # minus    -> hyphen
        ("Royal-Chain", "royal-chain"),
    ],
)
def test_normalisation_table(raw: str, expected: str) -> None:
    """SECTORS_EXPLAINED.md section 3, case for case."""
    assert normalize_key(raw) == expected


@pytest.mark.parametrize(
    "other", ["RoyalChain", "Royal-Chain", "Royal–Chain", "Royal_Chain"]
)
def test_spelling_that_must_not_match(other: str) -> None:
    """Legacy's config comments claim matching ignores "spacing and dash style".
    It does not: dash STYLE is unified, but dash-versus-space is not, and
    deleting a space breaks the match. Believing otherwise is how an operator
    ends up silently scoped to nothing."""
    assert normalize_key(other) != normalize_key("Royal Chain")


def test_parties_and_sectors_share_one_normalisation_rule(db_session) -> None:
    """legacy's normalizePartyKey_() was an alias of normalizeSectorKey_(), so a
    party name and a flow sector named after it produce the same key."""
    party = db_session.scalar(select(Party).where(Party.party_name == "Royal Chain"))
    assert party.party_key == normalize_key("Royal Chain")
    assert normalize_key(party.party_name) == party.party_key


def test_stored_keys_match_their_names(db_session) -> None:
    """A key that has drifted from its name silently breaks every lookup."""
    for row in db_session.scalars(select(Sector)):
        assert row.sector_key == normalize_key(row.sector_name)
    for row in db_session.scalars(select(FlowSector)):
        assert row.sector_key == normalize_key(row.sector_name)
    for row in db_session.scalars(select(Party)):
        assert row.party_key == normalize_key(row.party_name)
