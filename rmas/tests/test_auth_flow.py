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
