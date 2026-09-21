"""tests/test_staging_submission.py — the operator submission path.

Stage 1 of the two-stage workflow. The rules pinned here are the ones a
reasonable implementation gets wrong:

  * a submission is ONE SHOT per party per date, and stays blocked after the
    administrator commits — the rows go CONSUMED, not away
  * two operators on DIFFERENT parties must still be able to submit for the
    same date
  * operators submit Today's Required AND Today's Acquired, never `alloted`
  * a staged value of ZERO still overlays the administrator's screen: "we need
    nothing today" is a statement, not an absence
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models.party import Party
from models.sector import FlowSector, Sector
from models.staging import MetalRequirementStaging
from models.user import AppUser, UserPartyScope
from services.password_service import hash_password

PASSWORD = "correct horse battery staple"
DATE = "2026-10-01"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    royal = Party(party_name="Royal Chain", party_key="royal chain")
    aalishaan = Party(party_name="Aalishaan", party_key="aalishaan")
    session.add_all([royal, aalishaan])
    session.flush()

    for order, (name, party) in enumerate(
        [("RC Customer Orders", royal), ("RC Stock Orders", royal), ("AJ Orders", aalishaan)],
        start=1,
    ):
        session.add(
            Sector(
                sector_name=name,
                sector_key=name.lower(),
                priority=f"Priority {order}",
                purity="Any",
                party_id=party.party_id,
                display_order=order,
            )
        )
    for order, (name, party) in enumerate(
        [("Royal Chain", royal), ("Aalishaan", aalishaan)], start=1
    ):
        session.add(
            FlowSector(
                sector_name=name,
                sector_key=name.lower(),
                party_id=party.party_id,
                display_order=order,
            )
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


# Distinguishes "caller said nothing" from an explicit display_name=None, which
# is a real state: app_user.display_name is nullable.
_UNSET = object()


def _add_user(db, email, *, is_admin=False, party_name=None, display_name=_UNSET):
    user = AppUser(
        email=email,
        display_name=email if display_name is _UNSET else display_name,
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
    db.flush()
    return user


def _login(client, email):
    assert (
        client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )


def _ids(db, party_name):
    """(allocation sector ids, flow sector ids) owned by a party."""
    party = db.query(Party).filter_by(party_name=party_name).one()
    return (
        [s.sector_id for s in db.scalars(select(Sector).where(Sector.party_id == party.party_id))],
        [
            f.flow_sector_id
            for f in db.scalars(
                select(FlowSector).where(FlowSector.party_id == party.party_id)
            )
        ],
    )


def _payload(db, party_name, *, required="4.000", acquired="6.000", request_id="REQ-1"):
    sectors, flows = _ids(db, party_name)
    return {
        "allocations": [
            {"sector_id": sid, "today_required_kg": required if i == 0 else "0.000"}
            for i, sid in enumerate(sectors)
        ],
        "metal_flow": [{"flow_sector_id": fid, "today_acquired_kg": acquired} for fid in flows],
        "request_id": request_id,
    }


def _submit(client, db, party_name, **kw):
    return client.post(f"/staging/{DATE}", json=_payload(db, party_name, **kw))


# ----------------------------------------------------------------- happy path


def test_operator_can_submit(client, db_session) -> None:
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")

    response = _submit(client, db_session, "Royal Chain")
    assert response.status_code == 200, response.json()
    body = response.json()

    assert body["allocation_records"] == 2  # every in-scope sector, even the zero
    assert body["flow_records"] == 1
    assert body["total_required_kg"] == "4.000"
    assert body["total_acquired_kg"] == "6.000"
    assert body["submission_id"].startswith("SUB-")

    rows = db_session.scalars(select(MetalRequirementStaging)).all()
    assert len(rows) == 3
    assert {r.status for r in rows} == {"SUBMITTED"}
    assert {r.operator_email for r in rows} == {"op@royalchains.com"}


def test_submission_never_carries_alloted(client, db_session) -> None:
    """Allotment is the administrator's decision; the schema has no field for
    an operator to put one in, and staging stores a single value per row."""
    from schemas.staging import StagedAllocationInput

    assert "alloted_kg" not in StagedAllocationInput.model_fields
    assert set(StagedAllocationInput.model_fields) == {"sector_id", "today_required_kg"}


# ------------------------------------------------------------- the one-shot rule


def test_second_submission_is_blocked(client, db_session) -> None:
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")
    assert _submit(client, db_session, "Royal Chain").status_code == 200

    again = _submit(client, db_session, "Royal Chain", request_id="REQ-2")
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "ALREADY_SUBMITTED"


def test_block_is_audited(client, db_session) -> None:
    from models.audit import MetalAllocationAuditLog

    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")
    _submit(client, db_session, "Royal Chain")
    _submit(client, db_session, "Royal Chain", request_id="REQ-2")

    actions = [
        r.action_type for r in db_session.scalars(select(MetalAllocationAuditLog))
    ]
    assert "SUBMIT_REQUIREMENT" in actions
    assert "BLOCKED_RESUBMISSION" in actions


def test_a_colleague_on_the_same_party_is_also_blocked(client, db_session) -> None:
    """The submission is made on the party's behalf, not the person's."""
    _add_user(db_session, "op1@royalchains.com", party_name="Royal Chain")
    _add_user(db_session, "op2@royalchains.com", party_name="Royal Chain")

    _login(client, "op1@royalchains.com")
    assert _submit(client, db_session, "Royal Chain").status_code == 200

    _login(client, "op2@royalchains.com")
    blocked = _submit(client, db_session, "Royal Chain", request_id="REQ-2")
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "ALREADY_SUBMITTED"


def test_another_party_can_still_submit_for_the_same_date(client, db_session) -> None:
    """The block is per party, not per date — parties work independently."""
    _add_user(db_session, "rc@royalchains.com", party_name="Royal Chain")
    _add_user(db_session, "aj@royalchains.com", party_name="Aalishaan")

    _login(client, "rc@royalchains.com")
    assert _submit(client, db_session, "Royal Chain").status_code == 200

    _login(client, "aj@royalchains.com")
    assert _submit(client, db_session, "Aalishaan", request_id="REQ-2").status_code == 200


def test_consumed_rows_still_block(client, db_session) -> None:
    """After the administrator commits, the rows go CONSUMED — not away. The
    party stays closed for that date, or "cannot be changed once sent" would
    quietly reopen on every save."""
    from repository import staging_repo

    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")
    assert _submit(client, db_session, "Royal Chain").status_code == 200

    staging_repo.mark_consumed(db_session, DATE)
    db_session.flush()
    assert {r.status for r in db_session.scalars(select(MetalRequirementStaging))} == {
        "CONSUMED"
    }

    blocked = _submit(client, db_session, "Royal Chain", request_id="REQ-3")
    assert blocked.json()["detail"]["code"] == "ALREADY_SUBMITTED"


# ------------------------------------------------------------------ validation


def test_administrator_cannot_submit(client, db_session) -> None:
    _add_user(db_session, "admin@royalchains.com", is_admin=True, party_name="Royal Chain")
    _login(client, "admin@royalchains.com")

    response = _submit(client, db_session, "Royal Chain")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_CANNOT_SUBMIT"


def test_operator_with_no_party_is_refused(client, db_session) -> None:
    _add_user(db_session, "nobody@royalchains.com")
    _login(client, "nobody@royalchains.com")

    response = client.post(
        f"/staging/{DATE}", json={"allocations": [], "metal_flow": [], "request_id": "REQ-1"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NO_PARTY_ASSIGNED"


def test_zero_acquired_is_refused(client, db_session) -> None:
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")

    response = _submit(client, db_session, "Royal Chain", acquired="0.000")
    assert response.json()["detail"]["code"] == "NO_ACQUIRED_METAL"


def test_zero_required_is_refused(client, db_session) -> None:
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")

    response = _submit(client, db_session, "Royal Chain", required="0.000")
    assert response.json()["detail"]["code"] == "NO_REQUIREMENT"


def test_submitting_another_party_sector_is_a_trespass(client, db_session) -> None:
    """Not silently dropped — the operator is told their input was rejected."""
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")

    foreign, _ = _ids(db_session, "Aalishaan")
    payload = _payload(db_session, "Royal Chain")
    payload["allocations"].append({"sector_id": foreign[0], "today_required_kg": "9.000"})

    response = client.post(f"/staging/{DATE}", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SECTOR_NOT_IN_SCOPE"


def test_a_repeated_request_id_is_refused(client, db_session) -> None:
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _add_user(db_session, "other@royalchains.com", party_name="Aalishaan")
    _login(client, "op@royalchains.com")
    assert _submit(client, db_session, "Royal Chain").status_code == 200

    _login(client, "other@royalchains.com")
    replay = _submit(client, db_session, "Aalishaan", request_id="REQ-1")
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "DUPLICATE_REQUEST"


# --------------------------------------------------- the administrator's view


def test_staged_values_appear_on_the_administrator_screen(client, db_session) -> None:
    """The whole point: what the operator submits is what the admin sees."""
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _add_user(db_session, "admin@royalchains.com", is_admin=True)

    _login(client, "op@royalchains.com")
    assert _submit(client, db_session, "Royal Chain", required="4.250").status_code == 200

    _login(client, "admin@royalchains.com")
    model = client.get(f"/allocations/{DATE}").json()

    staged = {r["sector_name"]: r for r in model["allocations"] if r["from_submission"]}
    assert staged["RC Customer Orders"]["today_required_kg"] == "4.250"
    assert model["staged_value_count"] == 3
    # The admin is not locked out by somebody else's submission.
    assert model["already_submitted"] is False
    assert model["can_submit"] is False  # admins save, they do not submit


def test_a_staged_zero_still_overlays(client, db_session) -> None:
    """Presence is tested, not truthiness — "nothing needed today" is a fact."""
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _add_user(db_session, "admin@royalchains.com", is_admin=True)

    _login(client, "op@royalchains.com")
    _submit(client, db_session, "Royal Chain", required="4.000")

    _login(client, "admin@royalchains.com")
    model = client.get(f"/allocations/{DATE}").json()
    zero_row = next(
        r for r in model["allocations"] if r["sector_name"] == "RC Stock Orders"
    )
    assert zero_row["today_required_kg"] == "0.000"
    assert zero_row["from_submission"] is True


def test_operator_screen_locks_after_submitting(client, db_session) -> None:
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")

    before = client.get(f"/allocations/{DATE}").json()
    assert before["can_submit"] is True
    assert before["already_submitted"] is False

    _submit(client, db_session, "Royal Chain")

    after = client.get(f"/allocations/{DATE}").json()
    assert after["already_submitted"] is True
    assert after["can_submit"] is False


def test_an_operator_does_not_see_another_party_submission(client, db_session) -> None:
    _add_user(db_session, "rc@royalchains.com", party_name="Royal Chain")
    _add_user(db_session, "aj@royalchains.com", party_name="Aalishaan")

    _login(client, "rc@royalchains.com")
    _submit(client, db_session, "Royal Chain")

    _login(client, "aj@royalchains.com")
    model = client.get(f"/allocations/{DATE}").json()
    assert model["staged_value_count"] == 0
    assert model["already_submitted"] is False
    assert model["can_submit"] is True


# ------------------------------------------- announcing submissions to the admin

TIMESTAMP_DISPLAY = re.compile(r"^\d{2}-[A-Z][a-z]{2}-\d{4} \d{2}:\d{2}:\d{2}$")


def test_admin_sees_who_submitted_and_when(client, db_session) -> None:
    """The admin must know the figures in front of them came from an operator."""
    _add_user(
        db_session, "op@royalchains.com", party_name="Royal Chain", display_name="Snehal"
    )
    _add_user(db_session, "admin@royalchains.com", is_admin=True)

    _login(client, "op@royalchains.com")
    _submit(client, db_session, "Royal Chain")

    _login(client, "admin@royalchains.com")
    model = client.get(f"/allocations/{DATE}").json()

    assert len(model["submissions"]) == 1
    entry = model["submissions"][0]
    assert entry["party_name"] == "Royal Chain"
    assert entry["operator_name"] == "Snehal"
    assert entry["operator_email"] == "op@royalchains.com"
    # The FORMAT, never the value — the column is written in UTC while the app
    # timezone is Asia/Kolkata, and asserting a wall clock would pin that bug.
    assert TIMESTAMP_DISPLAY.match(entry["submitted_at_display"])

    # The two counts answer different questions and must never be confused: one
    # submission here covers 2 allocation sectors + 1 flow sector.
    assert model["staged_value_count"] == 3


def test_operator_name_falls_back_to_the_email_when_unset(client, db_session) -> None:
    """display_name is nullable, and a submission must never show up unnamed."""
    _add_user(
        db_session, "op@royalchains.com", party_name="Royal Chain", display_name=None
    )
    _add_user(db_session, "admin@royalchains.com", is_admin=True)

    _login(client, "op@royalchains.com")
    _submit(client, db_session, "Royal Chain")

    _login(client, "admin@royalchains.com")
    model = client.get(f"/allocations/{DATE}").json()
    assert model["submissions"][0]["operator_name"] == "op@royalchains.com"


def test_two_parties_produce_two_submission_lines(client, db_session) -> None:
    _add_user(db_session, "rc@royalchains.com", party_name="Royal Chain")
    _add_user(db_session, "aj@royalchains.com", party_name="Aalishaan")
    _add_user(db_session, "admin@royalchains.com", is_admin=True)

    _login(client, "rc@royalchains.com")
    _submit(client, db_session, "Royal Chain")
    _login(client, "aj@royalchains.com")
    _submit(client, db_session, "Aalishaan", request_id="REQ-2")

    _login(client, "admin@royalchains.com")
    model = client.get(f"/allocations/{DATE}").json()

    # A set, not a list: datetime('now') has one-second granularity, so two
    # submissions in the same second have no guaranteed order between them.
    assert {s["party_name"] for s in model["submissions"]} == {"Royal Chain", "Aalishaan"}


def test_an_operator_never_receives_the_submissions_list(client, db_session) -> None:
    """Admin-only is the server's rule, not the browser's.

    The summary is already scope-filtered, so this operator could only ever have
    seen their OWN row — but they are given nothing at all.
    """
    _add_user(db_session, "op@royalchains.com", party_name="Royal Chain")
    _login(client, "op@royalchains.com")
    _submit(client, db_session, "Royal Chain")

    model = client.get(f"/allocations/{DATE}").json()
    assert model["already_submitted"] is True, "their own submission did register"
    assert model["submissions"] == []


def test_a_date_with_no_submissions_returns_an_empty_list(client, db_session) -> None:
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    model = client.get(f"/allocations/{DATE}").json()
    assert model["submissions"] == []
