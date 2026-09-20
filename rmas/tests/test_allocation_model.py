"""tests/test_allocation_model.py — the Daily Allocation screen model.

The highest-risk logic in the port: carry-forward. CLAUDE.md section 6, rules
4-5 — Monday looks back to Saturday, a skipped day must never silently reset a
balance to zero, and a sector's previous requirement is the source row's
BALANCE, not its previous requirement.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models.allocation import MetalMaster
from models.flow import MetalFlowMaster
from models.party import Party
from models.sector import FlowSector, Sector
from models.user import AppUser
from services.allocation_service import build_allocation_model
from services.scope_service import build_scope
from services.weight_service import grams_to_kg, kg_to_grams


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
    session.flush()
    yield session
    session.close()


@pytest.fixture()
def admin_scope(db):
    user = AppUser(
        user_id=1,
        email="admin@royalchains.com",
        display_name="Admin",
        is_admin=True,
        admin_denied=False,
        is_active=True,
        password_hash="unused",
    )
    party_ids = [p.party_id for p in db.query(Party).all()]
    return build_scope(user, party_ids=[], flow_sector_ids=[], all_party_ids=party_ids)


def _save_day(db, day: str, *, previous_kg: str, required_kg: str, alloted_kg: str,
              acquired_kg: str = "0"):
    """Commit one day's rows the way the save path will."""
    sector = db.query(Sector).one()
    flow_sector = db.query(FlowSector).one()
    prev_g = kg_to_grams(Decimal(previous_kg))
    req_g = kg_to_grams(Decimal(required_kg))
    alloted_g = kg_to_grams(Decimal(alloted_kg))
    db.add(
        MetalMaster(
            allocation_date=day,
            sector_id=sector.sector_id,
            party_id=sector.party_id,
            priority_snapshot=sector.priority,
            purity_snapshot=sector.purity,
            previous_requirement_g=prev_g,
            today_required_g=req_g,
            alloted_g=alloted_g,
            balance_g=prev_g + req_g - alloted_g,
            saved_by="admin@royalchains.com",
        )
    )
    db.add(
        MetalFlowMaster(
            allocation_date=day,
            flow_sector_id=flow_sector.flow_sector_id,
            party_id=flow_sector.party_id,
            acquired_g=kg_to_grams(Decimal(acquired_kg)),
            saved_by="admin@royalchains.com",
        )
    )
    db.flush()


def test_monday_looks_back_to_saturday(db, admin_scope) -> None:
    """2026-08-17 is a Monday; its rule date is Saturday 2026-08-15."""
    _save_day(db, "2026-08-15", previous_kg="0", required_kg="10", alloted_kg="4")  # balance 6
    # A Sunday row that must NOT be picked, to prove -2 is real and not just
    # "the most recent row".
    _save_day(db, "2026-08-16", previous_kg="0", required_kg="99", alloted_kg="0")

    model = build_allocation_model(db, date(2026, 8, 17), admin_scope)

    assert model.rule_source_date == date(2026, 8, 15)
    assert model.previous_source_date == date(2026, 8, 15)
    assert model.used_fallback_source is False
    assert grams_to_kg(model.allocations[0].previous_requirement_g) == Decimal("6.000")


def test_other_days_look_back_one_day(db, admin_scope) -> None:
    _save_day(db, "2026-08-18", previous_kg="0", required_kg="7.5", alloted_kg="2.25")

    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)

    assert model.rule_source_date == date(2026, 8, 18)
    assert grams_to_kg(model.allocations[0].previous_requirement_g) == Decimal("5.250")


def test_previous_requirement_is_the_source_rows_balance(db, admin_scope) -> None:
    """Not the source row's own previous_requirement — yesterday's CLOSING
    balance is today's opening demand."""
    _save_day(db, "2026-08-18", previous_kg="100", required_kg="10", alloted_kg="30")
    # balance = 100 + 10 - 30 = 80

    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)

    assert grams_to_kg(model.allocations[0].previous_requirement_g) == Decimal("80.000")


def test_skipped_days_fall_back_to_latest_saved(db, admin_scope) -> None:
    """A gap must never silently reset the balance to zero (rule 5)."""
    _save_day(db, "2026-08-10", previous_kg="0", required_kg="12", alloted_kg="0")  # balance 12

    # Nothing saved on the 18th (the rule date for the 19th).
    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)

    assert model.rule_source_date == date(2026, 8, 18)
    assert model.previous_source_date == date(2026, 8, 10), "should report the REAL source"
    assert model.used_fallback_source is True
    assert grams_to_kg(model.allocations[0].previous_requirement_g) == Decimal("12.000")


def test_no_history_at_all_gives_zero(db, admin_scope) -> None:
    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)

    assert model.has_previous_data is False
    assert model.allocations[0].previous_requirement_g == 0
    assert model.allocations[0].balance_g == 0


def test_unsaved_day_balance_equals_previous_requirement(db, admin_scope) -> None:
    """With nothing entered yet, the closing balance is just what was carried in."""
    _save_day(db, "2026-08-18", previous_kg="0", required_kg="9", alloted_kg="0")

    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)
    row = model.allocations[0]

    assert row.today_required_g == 0
    assert row.alloted_g == 0
    assert row.balance_g == row.previous_requirement_g == kg_to_grams(Decimal("9"))


def test_a_saved_day_reports_its_stored_values(db, admin_scope) -> None:
    _save_day(db, "2026-08-19", previous_kg="5", required_kg="3", alloted_kg="2")

    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)
    row = model.allocations[0]

    assert model.is_saved is True
    assert grams_to_kg(row.previous_requirement_g) == Decimal("5.000")
    assert grams_to_kg(row.today_required_g) == Decimal("3.000")
    assert grams_to_kg(row.alloted_g) == Decimal("2.000")
    assert grams_to_kg(row.balance_g) == Decimal("6.000")


def test_negative_balance_carries_forward(db, admin_scope) -> None:
    """Allocating more than required is legitimate and the negative carries —
    which is why previous_requirement uses assert_signed_weight, not the
    non-negative check."""
    _save_day(db, "2026-08-18", previous_kg="0", required_kg="5", alloted_kg="8")
    # balance = 0 + 5 - 8 = -3

    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)

    assert grams_to_kg(model.allocations[0].previous_requirement_g) == Decimal("-3.000")


def test_flow_carries_previous_acquired(db, admin_scope) -> None:
    _save_day(db, "2026-08-18", previous_kg="0", required_kg="1", alloted_kg="0",
              acquired_kg="4.125")

    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)

    assert grams_to_kg(model.metal_flow[0].previous_acquired_g) == Decimal("4.125")
    assert model.metal_flow[0].today_acquired_g == 0


def test_totals_are_exact_over_many_rows(db, admin_scope) -> None:
    """1000 sectors each carrying 0.001 kg sum to exactly 1.000 kg.

    A float-backed store would drift here; integer grams cannot. This is the
    aggregate counterpart to tests/test_weight_service.py's per-value proof.
    """
    party = db.query(Party).one()
    for i in range(2, 1002):
        db.add(
            Sector(
                sector_name=f"S{i}",
                sector_key=f"s{i}",
                priority="Priority 1",
                purity="Any",
                party_id=party.party_id,
                display_order=i,
            )
        )
    db.flush()

    # Each sector closed yesterday with a balance of exactly 1 gram.
    for sector in db.query(Sector).all():
        db.add(
            MetalMaster(
                allocation_date="2026-08-18",
                sector_id=sector.sector_id,
                party_id=party.party_id,
                priority_snapshot=sector.priority,
                purity_snapshot=sector.purity,
                previous_requirement_g=0,
                today_required_g=1,
                alloted_g=0,
                balance_g=1,
                saved_by="admin@royalchains.com",
            )
        )
    db.flush()

    model = build_allocation_model(db, date(2026, 8, 19), admin_scope)

    assert len(model.allocations) == 1001
    # 1001 sectors x 1 gram carried forward.
    assert model.totals.total_previous_requirement_g == 1001
    assert grams_to_kg(model.totals.total_previous_requirement_g) == Decimal("1.001")
