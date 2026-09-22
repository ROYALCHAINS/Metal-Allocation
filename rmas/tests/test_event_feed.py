"""tests/test_event_feed.py — the notification feed behind the toast pop-ups.

The rules that matter, and that a reasonable implementation gets wrong:

  * the FIRST call returns a baseline and NO events, or every page load would
    replay the whole audit log as pop-ups
  * an administrator hears about submissions; an operator hears about saves and
    revisions — never the other way round
  * nobody is told about their own action
  * no weight ever crosses this boundary
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models.audit import MetalAllocationAuditLog
from models.user import AppUser
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


def _user(db, email, *, is_admin=False, display_name=None):
    db.add(
        AppUser(
            email=email,
            display_name=display_name,
            is_admin=is_admin,
            admin_denied=False,
            is_active=True,
            password_hash=hash_password(PASSWORD),
        )
    )
    db.commit()


def _login(client, email):
    assert (
        client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )


def _entry(db, *, action, email, date="2026-09-23", status="SUCCESS", audit_id=None):
    db.add(
        MetalAllocationAuditLog(
            audit_id=audit_id or f"AUD-{action}-{email}-{db.query(MetalAllocationAuditLog).count()}",
            allocation_date=date,
            action_type=action,
            action_status=status,
            revision_number=0,
            user_email=email,
        )
    )
    db.commit()


def test_the_first_call_takes_a_baseline_and_shows_nothing(client, db_session) -> None:
    """Otherwise every page load fires a pop-up for the entire history."""
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com")
    _entry(db_session, action="SUBMIT_REQUIREMENT", email="op@royalchains.com")
    _login(client, "admin@royalchains.com")

    body = client.get("/events").json()
    assert body["events"] == []
    assert body["cursor"] > 0, "the baseline is the current position, not zero"


def test_an_administrator_is_told_about_a_submission(client, db_session) -> None:
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com", display_name="Snehal")
    _login(client, "admin@royalchains.com")

    baseline = client.get("/events").json()["cursor"]
    _entry(db_session, action="SUBMIT_REQUIREMENT", email="op@royalchains.com")

    body = client.get("/events", params={"after": baseline}).json()
    assert len(body["events"]) == 1
    event = body["events"][0]
    assert event["kind"] == "submission"
    assert "Snehal" in event["message"], "the display name, not the raw email"
    assert "23-Sep-2026" in event["message"]
    assert body["cursor"] > baseline


def test_an_operator_is_told_about_a_save_and_a_revision(client, db_session) -> None:
    _user(db_session, "admin@royalchains.com", is_admin=True, display_name="Shubham")
    _user(db_session, "op@royalchains.com")
    _login(client, "op@royalchains.com")

    baseline = client.get("/events").json()["cursor"]
    _entry(db_session, action="SAVE", email="admin@royalchains.com")
    _entry(db_session, action="REVISE", email="admin@royalchains.com")

    events = client.get("/events", params={"after": baseline}).json()["events"]
    assert [e["kind"] for e in events] == ["save", "revision"], "oldest first"
    assert "finalised" in events[0]["message"]
    assert "revised" in events[1]["message"]


def test_the_roles_do_not_hear_each_others_events(client, db_session) -> None:
    """An administrator must not be toasted about their own saves, and an
    operator must not be toasted about another operator's submission."""
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com")
    _user(db_session, "op2@royalchains.com")

    _login(client, "admin@royalchains.com")
    admin_baseline = client.get("/events").json()["cursor"]
    _entry(db_session, action="SAVE", email="admin@royalchains.com")
    assert client.get("/events", params={"after": admin_baseline}).json()["events"] == []

    _login(client, "op@royalchains.com")
    op_baseline = client.get("/events").json()["cursor"]
    _entry(db_session, action="SUBMIT_REQUIREMENT", email="op2@royalchains.com")
    assert client.get("/events", params={"after": op_baseline}).json()["events"] == []


def test_nobody_is_told_about_their_own_action(client, db_session) -> None:
    """The actor already saw a confirmation banner."""
    _user(db_session, "op@royalchains.com")
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    baseline = client.get("/events").json()["cursor"]
    _entry(db_session, action="SUBMIT_REQUIREMENT", email="admin@royalchains.com")
    _entry(db_session, action="SUBMIT_REQUIREMENT", email="op@royalchains.com")

    events = client.get("/events", params={"after": baseline}).json()["events"]
    assert len(events) == 1, "the operator's submission only; not the admin's own"
    assert all("admin@royalchains.com" not in e["message"] for e in events)


def test_failed_and_blocked_entries_never_toast(client, db_session) -> None:
    """The feed announces what happened, not what was attempted — that is the
    Audit Log's job, and a failed submission is not news to an administrator."""
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com")
    _login(client, "admin@royalchains.com")

    baseline = client.get("/events").json()["cursor"]
    _entry(
        db_session,
        action="FAILED_SUBMISSION",
        email="op@royalchains.com",
        status="FAILED",
    )
    _entry(
        db_session,
        action="BLOCKED_RESUBMISSION",
        email="op@royalchains.com",
        status="BLOCKED",
    )

    assert client.get("/events", params={"after": baseline}).json()["events"] == []


def test_the_cursor_advances_so_an_event_toasts_once(client, db_session) -> None:
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com")
    _login(client, "admin@royalchains.com")

    cursor = client.get("/events").json()["cursor"]
    _entry(db_session, action="SUBMIT_REQUIREMENT", email="op@royalchains.com")

    first = client.get("/events", params={"after": cursor}).json()
    assert len(first["events"]) == 1

    second = client.get("/events", params={"after": first["cursor"]}).json()
    assert second["events"] == [], "the same event must not toast twice"


def test_the_feed_carries_no_weights(client, db_session) -> None:
    """An operator is told a date was finalised without being told anybody's
    figures, which is why this response needs no per-party scope filter."""
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com")
    _login(client, "op@royalchains.com")

    baseline = client.get("/events").json()["cursor"]
    _entry(db_session, action="SAVE", email="admin@royalchains.com")

    response = client.get("/events", params={"after": baseline})
    assert response.status_code == 200
    for field in ("_kg", "alloted", "balance", "acquired", "required"):
        assert field not in response.text


def test_the_feed_requires_a_session(client) -> None:
    assert client.get("/events").status_code == 401


# ------------------------------------------------- offline -> online catch-up
#
# The cursor lives in the browser's localStorage, keyed per account, so it
# SURVIVES SIGN-OUT. These pin the server half of that: polling from a cursor
# taken before the sign-out must return everything that happened in between.
# A per-page-load baseline could not do this, and did not — an event raised
# while a user was signed out was skipped permanently.


def test_events_raised_while_signed_out_arrive_on_the_next_sign_in(
    client, db_session
) -> None:
    """The administrator's case: an operator submits while they are away."""
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com", display_name="Snehal")

    _login(client, "admin@royalchains.com")
    cursor = client.get("/events").json()["cursor"]
    client.post("/auth/logout")

    _entry(db_session, action="SUBMIT_REQUIREMENT", email="op@royalchains.com")
    _entry(
        db_session,
        action="SUBMIT_REQUIREMENT",
        email="op@royalchains.com",
        date="2026-09-24",
    )

    _login(client, "admin@royalchains.com")
    events = client.get("/events", params={"after": cursor}).json()["events"]
    assert len(events) == 2, "both missed submissions, not none"
    assert all("Snehal" in e["message"] for e in events)


def test_the_operator_hears_about_a_save_made_while_they_were_away(
    client, db_session
) -> None:
    """The mirror case, which is the half that would be easy to leave out."""
    _user(db_session, "admin@royalchains.com", is_admin=True, display_name="Shubham")
    _user(db_session, "op@royalchains.com")

    _login(client, "op@royalchains.com")
    cursor = client.get("/events").json()["cursor"]
    client.post("/auth/logout")

    _entry(db_session, action="SAVE", email="admin@royalchains.com")
    _entry(db_session, action="REVISE", email="admin@royalchains.com")

    _login(client, "op@royalchains.com")
    events = client.get("/events", params={"after": cursor}).json()["events"]
    assert [e["kind"] for e in events] == ["save", "revision"]


def test_catching_up_does_not_replay_on_the_sign_in_after_that(
    client, db_session
) -> None:
    """Catch-up must be once. The cursor the client stores after the catch-up
    poll has to leave those events behind."""
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com")

    _login(client, "admin@royalchains.com")
    cursor = client.get("/events").json()["cursor"]
    client.post("/auth/logout")
    _entry(db_session, action="SUBMIT_REQUIREMENT", email="op@royalchains.com")

    _login(client, "admin@royalchains.com")
    caught_up = client.get("/events", params={"after": cursor}).json()
    assert len(caught_up["events"]) == 1
    client.post("/auth/logout")

    _login(client, "admin@royalchains.com")
    again = client.get("/events", params={"after": caught_up["cursor"]}).json()
    assert again["events"] == [], "the same event must not toast on every sign-in"


def test_two_accounts_on_one_browser_keep_separate_positions(
    client, db_session
) -> None:
    """localStorage is keyed per account, so one person signing in must not
    consume the notifications waiting for the other."""
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com")

    _login(client, "admin@royalchains.com")
    admin_cursor = client.get("/events").json()["cursor"]
    _login(client, "op@royalchains.com")
    op_cursor = client.get("/events").json()["cursor"]

    _entry(db_session, action="SUBMIT_REQUIREMENT", email="op@royalchains.com")

    _login(client, "admin@royalchains.com")
    assert len(client.get("/events", params={"after": admin_cursor}).json()["events"]) == 1

    _login(client, "op@royalchains.com")
    assert client.get("/events", params={"after": op_cursor}).json()["events"] == []


def test_a_long_absence_is_delivered_in_one_poll(client, db_session) -> None:
    """The limit is a safety bound, not a page size: draining a backlog a few
    at a time would make the client summarise it once per poll."""
    _user(db_session, "admin@royalchains.com", is_admin=True)
    _user(db_session, "op@royalchains.com")

    _login(client, "admin@royalchains.com")
    cursor = client.get("/events").json()["cursor"]
    for _ in range(30):
        _entry(db_session, action="SUBMIT_REQUIREMENT", email="op@royalchains.com")

    events = client.get("/events", params={"after": cursor}).json()["events"]
    assert len(events) == 30, "all 30 in a single response"
