"""tests/test_sector_scoping.py — an operator sees only their party's sectors.

CLAUDE.md section 6, rule 8: scope is resolved server-side on every request and
applied in the query. The client never gets to say which party it wants. These
tests go through the real HTTP endpoint, not just the service function, so the
whole chain is covered: session -> user -> scope -> SQL WHERE -> response.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models.party import Party
from models.sector import FlowSector, Sector
from models.user import AppUser, UserFlowScope, UserPartyScope
from services.password_service import hash_password

PASSWORD = "correct horse battery staple"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    # Two parties, each with one allocation sector and one flow sector.
    royal = Party(party_name="Royal Chain", party_key="royal chain")
    aalishaan = Party(party_name="Aalishaan", party_key="aalishaan")
    session.add_all([royal, aalishaan])
    session.flush()

    session.add_all(
        [
            Sector(
                sector_name="RC Customer Orders",
                sector_key="rc customer orders",
                priority="Priority 1",
                purity="Any",
                party_id=royal.party_id,
                display_order=1,
            ),
            Sector(
                sector_name="AJ Customer Orders",
                sector_key="aj customer orders",
                priority="Priority 1",
                purity="Any",
                party_id=aalishaan.party_id,
                display_order=2,
            ),
            FlowSector(
                sector_name="RC Customer Orders",
                sector_key="rc customer orders",
                party_id=royal.party_id,
                display_order=1,
            ),
            FlowSector(
                sector_name="AJ Customer Orders",
                sector_key="aj customer orders",
                party_id=aalishaan.party_id,
                display_order=2,
            ),
        ]
    )
    session.flush()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _add_user(db, email, *, is_admin=False, party_name=None, flow_sector_name=None):
    user = AppUser(
        email=email,
        display_name=email,
        is_admin=is_admin,
        admin_denied=False,
        is_active=True,
        password_hash=hash_password(PASSWORD),
    )
    db.add(user)
    db.flush()
    if party_name:
        party = db.query(Party).filter_by(party_name=party_name).one()
        db.add(UserPartyScope(user_id=user.user_id, party_id=party.party_id))
    if flow_sector_name:
        flow = db.query(FlowSector).filter_by(sector_name=flow_sector_name).one()
        db.add(UserFlowScope(user_id=user.user_id, flow_sector_id=flow.flow_sector_id))
    db.flush()
    return user


def _login(client, email):
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response


def test_operator_sees_only_their_own_party(client, db_session) -> None:
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")

    body = client.get("/sectors").json()
    alloc = [s["sector_name"] for s in body["allocation_sectors"]]
    parties = {s["party_name"] for s in body["allocation_sectors"]}

    assert alloc == ["RC Customer Orders"]
    assert parties == {"Royal Chain"}
    assert "AJ Customer Orders" not in alloc


def test_operator_flow_sectors_are_scoped_too(client, db_session) -> None:
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")

    body = client.get("/sectors").json()
    assert [s["party_name"] for s in body["flow_sectors"]] == ["Royal Chain"]


def test_admin_sees_every_party(client, db_session) -> None:
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    body = client.get("/sectors").json()
    assert {s["party_name"] for s in body["allocation_sectors"]} == {"Royal Chain", "Aalishaan"}
    assert len(body["flow_sectors"]) == 2


def test_denied_admin_is_scoped_like_an_operator(client, db_session) -> None:
    """The deny list overrides the admin grant (rule 9) — including for scope,
    not just for the role label."""
    user = _add_user(db_session, "denied@royalchains.com", is_admin=True, party_name="Aalishaan")
    user.admin_denied = True
    db_session.flush()
    _login(client, "denied@royalchains.com")

    body = client.get("/sectors").json()
    assert {s["party_name"] for s in body["allocation_sectors"]} == {"Aalishaan"}


def test_operator_with_no_party_grant_sees_nothing(client, db_session) -> None:
    """Fails closed: a misconfigured operator gets an empty list, not everything."""
    _add_user(db_session, "nobody@royalchains.com")
    _login(client, "nobody@royalchains.com")

    body = client.get("/sectors").json()
    assert body["allocation_sectors"] == []
    assert body["flow_sectors"] == []


def test_explicit_flow_grant_narrows_beyond_party(client, db_session) -> None:
    """StagingService.gs's scopeAllowsFlow_(): an explicit user_flow_scope list
    wins over the party fallback."""
    _add_user(
        db_session,
        "op@royalchains.com",
        party_name="Royal Chain",
        flow_sector_name="AJ Customer Orders",
    )
    _login(client, "op@royalchains.com")

    body = client.get("/sectors").json()
    # Flow follows the explicit grant, not the party…
    assert [s["sector_name"] for s in body["flow_sectors"]] == ["AJ Customer Orders"]
    # …while allocation sectors still follow the party.
    assert [s["sector_name"] for s in body["allocation_sectors"]] == ["RC Customer Orders"]


def test_sectors_requires_authentication(client) -> None:
    assert client.get("/sectors").status_code == 401
