"""tests/test_auth_flow.py — username/password login: closed roster + session cookie.

CLAUDE.md section 6, rule 11. The database is an in-memory SQLite stand-in
via dependency override.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models.user import AppUser
from services.password_service import hash_password


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    session = testing_session_local()
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


def _create_user(
    db_session,
    email="admin@royalchains.com",
    password="correct horse battery staple",
    is_admin=True,
):
    user = AppUser(
        email=email,
        display_name="Admin",
        is_admin=is_admin,
        admin_denied=False,
        is_active=True,
        password_hash=hash_password(password),
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_login_with_correct_credentials_sets_session(client, db_session) -> None:
    _create_user(db_session, email="admin@royalchains.com", password="correct horse battery staple")

    response = client.post(
        "/auth/login", json={"email": "admin@royalchains.com", "password": "correct horse battery staple"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@royalchains.com"
    assert body["role"] == "admin"

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@royalchains.com"


def test_login_with_wrong_password_rejected(client, db_session) -> None:
    _create_user(db_session, email="admin@royalchains.com", password="correct horse battery staple")

    response = client.post("/auth/login", json={"email": "admin@royalchains.com", "password": "wrong password"})
    assert response.status_code == 401


def test_login_with_unknown_email_rejected(client) -> None:
    """Closed roster: an email not in `users` is rejected, not auto-provisioned."""
    response = client.post("/auth/login", json={"email": "stranger@example.com", "password": "anything"})
    assert response.status_code == 401


def test_unknown_email_and_wrong_password_give_identical_error(client, db_session) -> None:
    """Never leak whether the account exists (routers/auth.py's comment)."""
    _create_user(db_session, email="admin@royalchains.com", password="correct horse battery staple")

    wrong_password = client.post(
        "/auth/login", json={"email": "admin@royalchains.com", "password": "wrong password"}
    )
    unknown_email = client.post("/auth/login", json={"email": "nobody@example.com", "password": "anything"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_me_requires_authentication(client) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_logout_clears_session(client, db_session) -> None:
    _create_user(db_session, email="admin@royalchains.com", password="correct horse battery staple")
    client.post("/auth/login", json={"email": "admin@royalchains.com", "password": "correct horse battery staple"})

    assert client.get("/auth/me").status_code == 200
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401


def test_denied_user_can_still_log_in_but_reports_as_operator(client, db_session) -> None:
    """The deny flag overrides admin status (rule 9), it does not block login itself —
    matching legacy, where NON_ADMIN_EMAILS only ever affected isAdministrator_()."""
    user = _create_user(db_session, email="denied@royalchains.com", password="password123", is_admin=True)
    user.admin_denied = True
    db_session.commit()

    response = client.post(
        "/auth/login", json={"email": "denied@royalchains.com", "password": "password123"}
    )
    assert response.status_code == 200
    # Logged in fine, but the deny list suppresses admin status.
    assert response.json()["role"] == "operator"


def test_inactive_account_cannot_log_in(client, db_session) -> None:
    user = _create_user(db_session, email="gone@royalchains.com", password="password123")
    user.is_active = False
    db_session.commit()

    response = client.post(
        "/auth/login", json={"email": "gone@royalchains.com", "password": "password123"}
    )
    assert response.status_code == 403


# -------------------------------------------------- deactivation mid-session
#
# Refusing an inactive account at LOGIN only guards the moment of sign-in.
# These pin the other half: a user deactivated while holding a valid session
# loses access on their very next request, on every endpoint, rather than
# keeping it until the cookie expires.


def _deactivate(db_session, email: str) -> None:
    user = db_session.query(AppUser).filter(AppUser.email == email).one()
    user.is_active = False
    db_session.commit()


def test_deactivation_ends_an_existing_session(client, db_session) -> None:
    _create_user(db_session, email="admin@royalchains.com", password=PASSWORD)
    client.post("/auth/login", json={"email": "admin@royalchains.com", "password": PASSWORD})
    assert client.get("/auth/me").status_code == 200, "precondition: the session works"

    _deactivate(db_session, "admin@royalchains.com")

    assert client.get("/auth/me").status_code == 401


def test_deactivation_clears_the_session_rather_than_just_refusing_it(
    client, db_session
) -> None:
    """The cookie must be discarded, not merely rejected on each request.

    Otherwise the browser keeps presenting a credential the server has already
    decided is dead, and reactivating the account would silently resurrect a
    session nobody signed in for.
    """
    _create_user(db_session, email="admin@royalchains.com", password=PASSWORD)
    client.post("/auth/login", json={"email": "admin@royalchains.com", "password": PASSWORD})
    _deactivate(db_session, "admin@royalchains.com")

    first = client.get("/auth/me")
    assert first.status_code == 401
    assert first.json()["detail"] == "This account is no longer active"

    # Session cleared, so the next request has no user_id at all — a different
    # branch, and the proof that the cookie went rather than being re-refused.
    second = client.get("/auth/me")
    assert second.status_code == 401
    assert second.json()["detail"] == "Not authenticated"


@pytest.mark.parametrize(
    "path",
    [
        "/auth/me",
        "/auth/access-diagnostics",
        "/sectors",
        "/allocations/2026-09-01",
        "/reports/counts",
        "/reports/allocation-history",
        "/reports/dashboard",
    ],
)
def test_deactivation_applies_to_every_endpoint(client, db_session, path) -> None:
    """The gate lives in get_current_user, so it must hold everywhere that
    depends on it — not only on the auth routes."""
    _create_user(db_session, email="admin@royalchains.com", password=PASSWORD)
    client.post("/auth/login", json={"email": "admin@royalchains.com", "password": PASSWORD})
    _deactivate(db_session, "admin@royalchains.com")

    assert client.get(path).status_code == 401


def test_a_deactivated_administrator_loses_the_audit_log(client, db_session) -> None:
    """The audit log holds identities and full before/after snapshots, so a
    deactivated admin reaching it is the worst case of this bug. 401, not 403:
    the session ended, so the question of admin rights never arises."""
    _create_user(db_session, email="admin@royalchains.com", password=PASSWORD, is_admin=True)
    client.post("/auth/login", json={"email": "admin@royalchains.com", "password": PASSWORD})
    assert client.get("/audit").status_code == 200, "precondition: admin can read the log"

    _deactivate(db_session, "admin@royalchains.com")

    assert client.get("/audit").status_code == 401


def test_a_deactivated_operator_cannot_submit(client, db_session) -> None:
    """A write path, not just reads — deactivation must stop the ledger being
    touched, not only stop screens rendering."""
    _create_user(db_session, email="op@royalchains.com", password=PASSWORD, is_admin=False)
    client.post("/auth/login", json={"email": "op@royalchains.com", "password": PASSWORD})
    _deactivate(db_session, "op@royalchains.com")

    response = client.post(
        "/staging/2026-09-01",
        json={"allocations": [], "metal_flow": [], "request_id": "REQ-deactivated"},
    )
    assert response.status_code == 401


def test_reactivation_restores_access_on_a_fresh_login(client, db_session) -> None:
    """Deactivation is reversible, and the fix must not strand a reinstated
    account — it ends the session, it does not brick the user."""
    _create_user(db_session, email="admin@royalchains.com", password=PASSWORD)
    client.post("/auth/login", json={"email": "admin@royalchains.com", "password": PASSWORD})
    _deactivate(db_session, "admin@royalchains.com")
    assert client.get("/auth/me").status_code == 401

    user = db_session.query(AppUser).filter(AppUser.email == "admin@royalchains.com").one()
    user.is_active = True
    db_session.commit()

    assert (
        client.post(
            "/auth/login", json={"email": "admin@royalchains.com", "password": PASSWORD}
        ).status_code
        == 200
    )
    assert client.get("/auth/me").status_code == 200


# --------------------------------------------------------- access diagnostics

PASSWORD = "correct horse battery staple"


def test_access_diagnostics_requires_a_session(client) -> None:
    assert client.get("/auth/access-diagnostics").status_code == 401


def test_an_operator_may_read_their_own_diagnostics(client, db_session) -> None:
    """The whole point: it answers "why can't I see the Audit Log?".

    Gating this on admin would refuse exactly the people who need it, so a 200
    here for a non-admin is the contract, not an oversight.
    """
    _create_user(db_session, email="op@royalchains.com", is_admin=False)
    client.post("/auth/login", json={"email": "op@royalchains.com", "password": PASSWORD})

    body = client.get("/auth/access-diagnostics").json()
    assert body["email"] == "op@royalchains.com"
    assert body["is_administrator"] is False
    assert body["admin_denied"] is False
    assert any("not flagged as an administrator" in line for line in body["diagnosis"])
    # No user_flow_scope rows, so the fallback branch — never "no access".
    assert body["flow_scope"] == "(none configured - falling back to the Party column)"


def test_a_denied_admin_reads_the_deny_reason(client, db_session) -> None:
    user = _create_user(db_session, email="denied@royalchains.com", is_admin=True)
    user.admin_denied = True
    db_session.commit()
    client.post("/auth/login", json={"email": "denied@royalchains.com", "password": PASSWORD})

    body = client.get("/auth/access-diagnostics").json()
    assert body["is_administrator"] is False, "the deny list beats an admin grant"
    assert body["admin_denied"] is True
    assert any("deny list" in line for line in body["diagnosis"])


def test_diagnostics_never_mention_another_account(client, db_session) -> None:
    """Rule 10 regression test.

    Legacy returned CONFIG.ADMIN_EMAILS and CONFIG.NON_ADMIN_EMAILS wholesale,
    so every caller learned the whole roster. Nothing but the caller's own
    address may appear anywhere in this response.
    """
    _create_user(db_session, email="admin@royalchains.com", is_admin=True)
    _create_user(db_session, email="op@royalchains.com", is_admin=False)
    client.post("/auth/login", json={"email": "op@royalchains.com", "password": PASSWORD})

    response = client.get("/auth/access-diagnostics")
    assert "admin@royalchains.com" not in response.text
    assert response.json()["email"] == "op@royalchains.com"


def test_diagnostics_accept_no_subject_parameter(client, db_session) -> None:
    """Legacy's debugScreenFlags let an admin inspect another user. Not ported."""
    _create_user(db_session, email="admin@royalchains.com", is_admin=True)
    _create_user(db_session, email="op@royalchains.com", is_admin=False)
    client.post("/auth/login", json={"email": "op@royalchains.com", "password": PASSWORD})

    plain = client.get("/auth/access-diagnostics").json()
    probed = client.get(
        "/auth/access-diagnostics",
        params={"email": "admin@royalchains.com", "subject": "admin@royalchains.com"},
    ).json()
    assert probed == plain
