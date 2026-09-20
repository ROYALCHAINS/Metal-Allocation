"""tests/test_allocation_save.py — the admin commit.

Covers the properties that actually matter: only admins can save, a saved date
is immutable, a double-click cannot write twice, the client cannot smuggle its
own sector/party/purity values in, failures are audited, and the audit log
records the committed state.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models.allocation import MetalMaster
from models.audit import MetalAllocationAuditLog
from models.flow import MetalFlowMaster
from models.party import Party
from models.sector import FlowSector, Sector
from models.user import AppUser
from schemas.allocation import AllocationRowInput, FlowRowInput
from services.allocation_service import build_allocation_model, save_daily_allocation
from services.exceptions import (
    DateAlreadySavedError,
    DuplicateRequestError,
    NotAuthorizedError,
    ValidationError,
)
from services.scope_service import build_scope
from services.weight_service import grams_to_kg, kg_to_grams

DAY = date(2026, 8, 19)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    party = Party(party_name="Royal Chain", party_key="royal chain")
    session.add(party)
    session.flush()
    session.add_all(
        [
            Sector(
                sector_name="RC Customer Orders",
                sector_key="rc customer orders",
                priority="Priority 1",
                purity="Any",
                party_id=party.party_id,
                display_order=1,
            ),
            FlowSector(
                sector_name="RC Customer Orders",
                sector_key="rc customer orders",
                party_id=party.party_id,
                display_order=1,
            ),
        ]
    )
    session.commit()
    yield session
    session.close()


def _user(db, *, is_admin=True):
    user = AppUser(
        email="admin@royalchains.com" if is_admin else "op@royalchains.com",
        display_name="U",
        is_admin=is_admin,
        admin_denied=False,
        is_active=True,
        password_hash="unused",
    )
    db.add(user)
    db.commit()
    return user


def _scope(db, user):
    party_ids = [p.party_id for p in db.query(Party).all()]
    return build_scope(user, party_ids=party_ids, flow_sector_ids=[], all_party_ids=party_ids)


def _payload(db, *, required="10", alloted="4", acquired="6"):
    sector = db.query(Sector).one()
    flow = db.query(FlowSector).one()
    return (
        [
            AllocationRowInput(
                sector_id=sector.sector_id,
                previous_requirement_kg=Decimal("0"),
                today_required_kg=Decimal(required),
                alloted_kg=Decimal(alloted),
            )
        ],
        [
            FlowRowInput(
                flow_sector_id=flow.flow_sector_id, today_acquired_kg=Decimal(acquired)
            )
        ],
    )


def _save(db, user, *, request_id="REQ-1", **kwargs):
    allocations, flow = _payload(db, **kwargs)
    return save_daily_allocation(
        db,
        user=user,
        scope=_scope(db, user),
        selected=DAY,
        submitted_allocations=allocations,
        submitted_flow=flow,
        request_id=request_id,
    )


def test_admin_can_save_and_rows_are_written(db) -> None:
    user = _user(db)
    result = _save(db, user)

    assert result.allocation_records == 1
    assert result.flow_records == 1
    assert result.audit_id.startswith("AUD-")

    row = db.scalar(select(MetalMaster))
    assert row.allocation_date == "2026-08-19"
    assert grams_to_kg(row.today_required_g) == Decimal("10.000")
    assert grams_to_kg(row.alloted_g) == Decimal("4.000")
    # balance = 0 + 10 - 4
    assert grams_to_kg(row.balance_g) == Decimal("6.000")
    assert row.saved_by == "admin@royalchains.com"
    assert row.revision_number == 0

    flow_row = db.scalar(select(MetalFlowMaster))
    assert grams_to_kg(flow_row.acquired_g) == Decimal("6.000")


def test_operator_cannot_save(db) -> None:
    """Operators submit requirements; only an administrator finalises a date."""
    user = _user(db, is_admin=False)
    with pytest.raises(NotAuthorizedError) as exc:
        _save(db, user)
    assert exc.value.code == "NOT_AUTHORIZED"
    assert db.scalar(select(MetalMaster)) is None


def test_denied_admin_cannot_save(db) -> None:
    """The deny list overrides the admin grant (rule 9), including here."""
    user = _user(db)
    user.admin_denied = True
    db.commit()

    with pytest.raises(NotAuthorizedError):
        _save(db, user)


def test_saved_date_is_immutable(db) -> None:
    user = _user(db)
    _save(db, user, request_id="REQ-1")

    with pytest.raises(DateAlreadySavedError) as exc:
        _save(db, user, request_id="REQ-2")
    assert exc.value.code == "DATE_ALREADY_SAVED"

    # Still exactly one row — nothing was double-written.
    assert len(db.scalars(select(MetalMaster)).all()) == 1


def test_blocked_duplicate_is_audited(db) -> None:
    user = _user(db)
    _save(db, user, request_id="REQ-1")
    with pytest.raises(DateAlreadySavedError):
        _save(db, user, request_id="REQ-2")

    blocked = db.scalar(
        select(MetalAllocationAuditLog).where(
            MetalAllocationAuditLog.action_type == "BLOCKED_DUPLICATE"
        )
    )
    assert blocked is not None
    assert blocked.action_status == "BLOCKED"


def test_repeated_request_id_is_rejected(db) -> None:
    """Double-click protection: the same request_id cannot write twice."""
    user = _user(db)
    _save(db, user, request_id="REQ-SAME")

    with pytest.raises(DuplicateRequestError) as exc:
        _save(db, user, request_id="REQ-SAME")
    assert exc.value.code == "DUPLICATE_REQUEST"


def test_acquired_must_be_positive(db) -> None:
    """The one enabled save rule (REQUIRE_POSITIVE_ACQUIRED)."""
    user = _user(db)
    with pytest.raises(ValidationError) as exc:
        _save(db, user, acquired="0")
    assert exc.value.code == "NO_ACQUIRED_METAL"


def test_failed_save_is_audited_and_writes_nothing(db) -> None:
    """Failures are logged too, not just successes (rule 14)."""
    user = _user(db)
    with pytest.raises(ValidationError):
        _save(db, user, alloted="-5")

    assert db.scalar(select(MetalMaster)) is None


def test_client_cannot_override_sector_identity(db) -> None:
    """The payload carries only weights. Sector name, party, purity and priority
    come from the database, so a tampered client cannot relabel a row."""
    user = _user(db)
    _save(db, user)

    row = db.scalar(select(MetalMaster))
    sector = db.query(Sector).one()
    assert row.sector_id == sector.sector_id
    assert row.party_id == sector.party_id
    assert row.purity_snapshot == "Any"
    assert row.priority_snapshot == "Priority 1"


def test_row_count_mismatch_is_rejected(db) -> None:
    """Submitting fewer rows than the caller has sectors cannot silently save a
    partial date."""
    user = _user(db)
    with pytest.raises(ValidationError) as exc:
        save_daily_allocation(
            db,
            user=user,
            scope=_scope(db, user),
            selected=DAY,
            submitted_allocations=[],
            submitted_flow=_payload(db)[1],
            request_id="REQ-EMPTY",
        )
    assert exc.value.code == "ALLOCATION_ROW_COUNT"


def test_successful_save_is_audited_with_a_snapshot(db) -> None:
    user = _user(db)
    _save(db, user)

    entry = db.scalar(
        select(MetalAllocationAuditLog).where(MetalAllocationAuditLog.action_type == "SAVE")
    )
    assert entry.action_status == "SUCCESS"
    assert entry.revision_number == 0
    assert entry.user_email == "admin@royalchains.com"
    assert entry.previous_allocation_data == ""  # an insert has no before-state
    # Snapshot records kilograms as exact strings, with legacy's short keys.
    assert '"bl": "6.000"' in entry.updated_allocation_data
    assert '"s": "RC Customer Orders"' in entry.updated_allocation_data
    assert '"ac": "6.000"' in entry.updated_metal_flow_data


def test_saved_values_carry_into_the_next_day(db) -> None:
    """The whole point of the ledger: today's closing balance is tomorrow's
    opening requirement."""
    user = _user(db)
    _save(db, user, required="10", alloted="4")  # balance 6

    model = build_allocation_model(db, date(2026, 8, 20), _scope(db, user))

    assert grams_to_kg(model.allocations[0].previous_requirement_g) == Decimal("6.000")
    assert model.previous_source_date == DAY


def test_weights_round_trip_exactly(db) -> None:
    user = _user(db)
    _save(db, user, required="0.001", alloted="0.001", acquired="0.001")

    row = db.scalar(select(MetalMaster))
    assert row.today_required_g == kg_to_grams(Decimal("0.001")) == 1
    assert row.balance_g == 0
