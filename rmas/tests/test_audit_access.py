"""tests/test_audit_access.py — the audit log's server-side gate.

This is the one module where an authorisation mistake is a serious problem
rather than a cosmetic one: the log holds user identities and full before/after
data snapshots.

Every test goes through the real HTTP endpoint, because hiding the nav tab in
the browser is convenience and the server check is the actual control. The deny
list beats an admin grant (rule 2), and anything unresolved fails closed.
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

ENDPOINTS = ["/audit", "/audit/filter-options", "/audit/entry/AUD-1"]


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        MetalAllocationAuditLog(
            audit_id="AUD-1",
            allocation_date="2026-09-01",
            action_type="SAVE",
            action_status="SUCCESS",
            revision_number=0,
            user_email="admin@royalchains.com",
            action_timestamp="2026-09-01 10:00:00",
            updated_allocation_data='[{"p":"Priority 1","s":"RC","pu":"Any",'
            '"pr":"0.000","tr":"5.000","al":"5.000","bl":"0.000"}]',
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


def _add_user(db, email, *, is_admin=False, admin_denied=False):
    user = AppUser(
        email=email,
        display_name=email,
        is_admin=is_admin,
        admin_denied=admin_denied,
        is_active=True,
        password_hash=hash_password(PASSWORD),
    )
    db.add(user)
    db.flush()
    return user


def _login(client, email):
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


@pytest.mark.parametrize("path", ENDPOINTS)
def test_anonymous_caller_is_refused(client, path) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ENDPOINTS)
def test_operator_is_refused_on_every_endpoint(client, db_session, path) -> None:
    """Not just the list — the filter options leak the roster of users who have
    touched the system, and the detail leaks full data snapshots."""
    _add_user(db_session, "op@royalchains.com")
    _login(client, "op@royalchains.com")
    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", ENDPOINTS)
def test_deny_list_beats_an_admin_grant(client, db_session, path) -> None:
    """Rule 2. An explicit denial wins even when is_admin is also set."""
    _add_user(db_session, "revoked@royalchains.com", is_admin=True, admin_denied=True)
    _login(client, "revoked@royalchains.com")
    assert client.get(path).status_code == 403


def test_administrator_sees_the_log(client, db_session) -> None:
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    body = client.get("/audit").json()
    assert body["summary"]["counts"] == {
        "total": 1,
        "success": 1,
        "blocked": 0,
        "failed": 0,
        "revisions": 0,
    }
    assert body["rows"][0]["audit_id"] == "AUD-1"
    assert body["rows"][0]["has_snapshots"] is True
    # The list must not carry snapshots (rule 8).
    assert "allocation_diff" not in body["rows"][0]


def test_missing_entry_reports_not_found_rather_than_an_empty_modal(
    client, db_session
) -> None:
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    response = client.get("/audit/entry/AUD-does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "AUDIT_ENTRY_NOT_FOUND"


def test_blocked_entry_has_no_snapshot_to_view(client, db_session) -> None:
    """A blocked or failed attempt captured nothing, so the page disables the
    View changes button rather than opening an empty comparison."""
    db_session.add(
        MetalAllocationAuditLog(
            audit_id="AUD-2",
            allocation_date="2026-09-02",
            action_type="BLOCKED_DUPLICATE",
            action_status="BLOCKED",
            revision_number=0,
            user_email="admin@royalchains.com",
            action_timestamp="2026-09-02 10:00:00",
        )
    )
    db_session.flush()
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    rows = {r["audit_id"]: r for r in client.get("/audit").json()["rows"]}
    assert rows["AUD-2"]["has_snapshots"] is False

    counts = client.get("/audit").json()["summary"]["counts"]
    assert counts["blocked"] == 1
    assert counts["success"] + counts["blocked"] + counts["failed"] == counts["total"]


def test_revisions_overlap_the_status_counts_and_are_not_added_in(
    client, db_session
) -> None:
    db_session.add(
        MetalAllocationAuditLog(
            audit_id="AUD-3",
            allocation_date="2026-09-01",
            action_type="REVISE",
            action_status="SUCCESS",
            revision_number=1,
            user_email="admin@royalchains.com",
            action_timestamp="2026-09-03 10:00:00",
            revision_reason="Corrected the allotment after a recount",
        )
    )
    db_session.flush()
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    counts = client.get("/audit").json()["summary"]["counts"]
    assert counts["total"] == 2
    assert counts["success"] == 2
    assert counts["revisions"] == 1, "a REVISE is also a SUCCESS, counted in both"


def test_truncation_is_reported_rather_than_paged(client, db_session) -> None:
    """Unlike the history pages, this flag is genuinely wired and does fire."""
    for n in range(5):
        db_session.add(
            MetalAllocationAuditLog(
                audit_id=f"AUD-bulk-{n}",
                allocation_date="2026-09-05",
                action_type="SAVE",
                action_status="SUCCESS",
                revision_number=0,
                user_email="admin@royalchains.com",
                action_timestamp=f"2026-09-05 10:00:0{n}",
            )
        )
    db_session.flush()
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    body = client.get("/audit?limit=3").json()
    assert body["summary"]["returned_count"] == 3
    assert body["summary"]["record_count"] == 6, "counted before truncation"
    assert body["summary"]["truncated"] is True
    # Newest first.
    assert body["rows"][0]["audit_id"] == "AUD-bulk-4"


def test_detail_returns_the_full_reason_not_the_preview(client, db_session) -> None:
    long_reason = "Recount after the vault audit. " * 10
    db_session.add(
        MetalAllocationAuditLog(
            audit_id="AUD-4",
            allocation_date="2026-09-01",
            action_type="REVISE",
            action_status="SUCCESS",
            revision_number=1,
            user_email="admin@royalchains.com",
            action_timestamp="2026-09-04 10:00:00",
            revision_reason=long_reason,
            previous_allocation_data='[{"s":"RC","pr":"0.000","tr":"5.000",'
            '"al":"5.000","bl":"0.000"}]',
            updated_allocation_data='[{"s":"RC","pr":"0.000","tr":"5.000",'
            '"al":"4.000","bl":"1.000"}]',
        )
    )
    db_session.flush()
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    row = next(r for r in client.get("/audit").json()["rows"] if r["audit_id"] == "AUD-4")
    assert len(row["reason_preview"]) == 140

    detail = client.get("/audit/entry/AUD-4").json()
    assert detail["reason"] == long_reason
    assert detail["changed_sectors"] == 1
    [entry] = detail["allocation_diff"]
    assert entry["changed"]["alloted"] is True
    assert entry["changed"]["today_required"] is False
    assert entry["before"]["alloted_kg"] == "5.000"
    assert entry["after"]["alloted_kg"] == "4.000"


def _add_undated_failure(db, audit_id="AUD-undated"):
    """A hard failure recorded before the allocation date was ever resolved."""
    db.add(
        MetalAllocationAuditLog(
            audit_id=audit_id,
            allocation_date=None,
            action_type="FAILED_SAVE",
            action_status="FAILED",
            revision_number=0,
            user_email="admin@royalchains.com",
            action_timestamp="2026-09-06 10:00:00",
        )
    )
    db.flush()


def test_an_undated_entry_can_be_recorded(client, db_session) -> None:
    """Migration 0004 made allocation_date nullable so this is possible at all.
    Before it, the failure the log most needs to capture could not be stored."""
    _add_undated_failure(db_session)
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    row = next(
        r for r in client.get("/audit").json()["rows"] if r["audit_id"] == "AUD-undated"
    )
    assert row["allocation_date"] is None
    # The page renders an em-dash for this, never a fabricated date.
    assert row["allocation_date_display"] is None


def test_undated_entry_survives_a_date_window(client, db_session) -> None:
    """Page spec rule 4. A plain `WHERE date BETWEEN ...` would drop exactly the
    failures the log exists to record, so the filter spares undated rows."""
    _add_undated_failure(db_session)
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    # A window that excludes the dated entry entirely.
    body = client.get("/audit?date_from=2030-01-01&date_to=2030-12-31").json()
    ids = [r["audit_id"] for r in body["rows"]]

    assert ids == ["AUD-undated"], "the undated failure must not be filtered out"
    assert "AUD-1" not in ids, "the dated entry is correctly outside the window"
    assert body["summary"]["counts"]["failed"] == 1


def test_undated_entry_is_still_filtered_by_its_other_fields(client, db_session) -> None:
    """Sparing them from the DATE window does not exempt them from everything."""
    _add_undated_failure(db_session)
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    ids = [r["audit_id"] for r in client.get("/audit?status=SUCCESS").json()["rows"]]
    assert "AUD-undated" not in ids


def test_a_malformed_date_is_still_rejected(db_session) -> None:
    """Nullable means "no date", not "any string". The empty string is neither
    a date nor NULL and must not sneak past the format CHECK."""
    from sqlalchemy.exc import IntegrityError

    db_session.add(
        MetalAllocationAuditLog(
            audit_id="AUD-malformed",
            allocation_date="not-a-date",
            action_type="FAILED_SAVE",
            action_status="FAILED",
            revision_number=0,
            user_email="admin@royalchains.com",
            action_timestamp="2026-09-06 10:00:00",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_filter_options_ignore_undated_entries_when_suggesting_a_range(
    client, db_session
) -> None:
    """An undated row has no date to bound the suggested window with."""
    _add_undated_failure(db_session)
    _add_user(db_session, "admin@royalchains.com", is_admin=True)
    _login(client, "admin@royalchains.com")

    options = client.get("/audit/filter-options").json()
    assert options["min_date"] == "2026-09-01"
    assert options["max_date"] == "2026-09-01"
    # But it still counts as an entry.
    assert options["entry_count"] == 2


def test_the_revision_summary_is_deliberately_not_admin_gated(client, db_session) -> None:
    """The one audit-derived payload an operator IS allowed to see.

    getDateRevisionSummary() is the single function in AuditReportService.gs
    that does not call assertAuditAccess_() — its docstring says "Safe for every
    user: returns counts and timestamps only, never snapshots". It rides on the
    allocation response for exactly that reason, so it must NOT be added to
    ENDPOINTS above, whose tests assert the opposite.
    """
    _add_user(db_session, "op@royalchains.com")
    _login(client, "op@royalchains.com")

    response = client.get("/allocations/2026-09-01")
    assert response.status_code == 200

    summary = response.json()["revision_summary"]
    assert summary["originally_saved_by"] == "admin@royalchains.com"
    # Stored as '2026-09-01 10:00:00' UTC by the fixture; displayed in the
    # application timezone, Asia/Kolkata (UTC+5:30) — resolved 2026-09-22.
    assert summary["originally_saved_at_display"] == "01-Sep-2026 15:30:00"
    assert summary["message"] == "This date has not been revised."
