"""tests/test_dashboard_rules.py — the Analysis Dashboard's two subtle rules.

Both are from PROMPT_analysis_dashboard.md and both are the kind of thing a
reasonable implementation gets wrong:

  Rule 2 — an ALLOCATION-sector filter must not blank the acquired series. The
  two ledgers keep separate sector tables, so pushing the filter blindly at the
  flow ledger makes the dashboard claim no metal arrived.

  Rule 5 — topPending reads each sector's balance on ITS OWN latest saved date,
  never a sum across the range. Balances carry forward, so summing counts the
  same outstanding metal once per day it stayed outstanding.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models.allocation import MetalMaster
from models.flow import MetalFlowMaster
from models.party import Party
from models.sector import FlowSector, Sector
from services.report_service import get_dashboard_summary
from services.scope_service import UserScope


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
    session.add(royal)
    session.flush()

    # "Stock Orders" exists on the demand side only — no flow sector matches it.
    for order, name in enumerate(["RC Customer Orders", "Stock Orders"], start=1):
        session.add(
            Sector(
                sector_name=name,
                sector_key=name.lower(),
                priority=f"Priority {order}",
                purity="Any",
                party_id=royal.party_id,
                display_order=order,
            )
        )
    session.add(
        FlowSector(
            sector_name="RC Customer Orders",
            sector_key="rc customer orders",
            party_id=royal.party_id,
            display_order=1,
        )
    )
    session.flush()

    sectors = {s.sector_name: s.sector_id for s in session.query(Sector).all()}
    flow_id = session.query(FlowSector).one().flow_sector_id

    # Two dates. "Stock Orders" clears on the second; its balance falls from
    # 5.000 kg to 1.000 kg, so a range SUM would report 6.000 and a correct
    # latest-date read reports 1.000.
    for day, (cust_balance, stock_balance) in {
        "2026-09-01": (3_000, 5_000),
        "2026-09-02": (2_000, 1_000),
    }.items():
        session.add_all(
            [
                MetalMaster(
                    allocation_date=day,
                    party_id=royal.party_id,
                    sector_id=sectors["RC Customer Orders"],
                    previous_requirement_g=0,
                    today_required_g=10_000,
                    alloted_g=10_000 - cust_balance,
                    balance_g=cust_balance,
                    purity_snapshot="Any",
                    priority_snapshot="Priority 1",
                    saved_by="admin@royalchains.com",
                ),
                MetalMaster(
                    allocation_date=day,
                    party_id=royal.party_id,
                    sector_id=sectors["Stock Orders"],
                    previous_requirement_g=0,
                    today_required_g=8_000,
                    alloted_g=8_000 - stock_balance,
                    balance_g=stock_balance,
                    purity_snapshot="Any",
                    priority_snapshot="Priority 2",
                    saved_by="admin@royalchains.com",
                ),
                MetalFlowMaster(
                    allocation_date=day,
                    party_id=royal.party_id,
                    flow_sector_id=flow_id,
                    acquired_g=7_000,
                    saved_by="admin@royalchains.com",
                ),
            ]
        )
    session.flush()
    yield session
    session.close()


@pytest.fixture()
def scope(db_session):
    party_ids = frozenset(p.party_id for p in db_session.query(Party).all())
    return UserScope(
        user_id=1,
        email="admin@royalchains.com",
        is_admin=True,
        unrestricted=True,
        party_ids=party_ids,
        # None, not an empty set: "no explicit grants, fall back to party".
        flow_sector_ids=None,
    )


def _summary(db, scope, **kw):
    return get_dashboard_summary(db, scope, date_from="2026-09-01", date_to="2026-09-02", **kw)


def test_sector_in_both_ledgers_filters_supply_too(db_session, scope) -> None:
    sector_id = (
        db_session.query(Sector).filter_by(sector_name="RC Customer Orders").one().sector_id
    )
    summary = _summary(
        db_session, scope, sector_id=sector_id, sector_name="RC Customer Orders"
    )
    assert summary.total_acquired_g == 14_000
    assert summary.flow_filter_skipped is False


def test_allocation_only_sector_does_not_blank_the_acquired_series(db_session, scope) -> None:
    """The whole point of rule 2: no flow sector is named "Stock Orders", so the
    supply side must be left alone rather than filtered down to nothing."""
    sector_id = db_session.query(Sector).filter_by(sector_name="Stock Orders").one().sector_id
    summary = _summary(db_session, scope, sector_id=sector_id, sector_name="Stock Orders")

    assert summary.total_acquired_g == 14_000, "acquired was blanked by a demand-side filter"
    assert summary.flow_filter_skipped is True
    # Demand, by contrast, IS filtered — unconditionally.
    assert summary.total_required_g == 16_000


def test_top_pending_reads_each_sector_latest_date_not_a_range_sum(db_session, scope) -> None:
    pending = {p.sector_name: p.pending_g for p in _summary(db_session, scope).top_pending}

    assert pending["Stock Orders"] == 1_000, "summed the range instead of reading the latest date"
    assert pending["RC Customer Orders"] == 2_000
    assert all(p.as_of == "2026-09-02" for p in _summary(db_session, scope).top_pending)


def test_top_pending_drops_cleared_sectors(db_session, scope) -> None:
    """A zero closing balance is a valid outcome, not a row for this table."""
    db_session.query(MetalMaster).filter_by(allocation_date="2026-09-02").update(
        {MetalMaster.balance_g: 0}
    )
    db_session.flush()
    assert _summary(db_session, scope).top_pending == []
