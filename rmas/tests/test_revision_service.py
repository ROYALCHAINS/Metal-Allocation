"""tests/test_revision_service.py — editing a saved date, and the forward cascade.

The cascade arithmetic is pinned in test_cascade_service.py. What matters here
is everything around it: the guard order, what each failure audits, and above
all ATOMICITY — a revision that fails part-way must leave the ledger and the
log exactly as it found them.

Two sectors across two parties, so "the untouched sector produces no cascade
entry" is a real assertion rather than a vacuous one.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models.allocation import MetalMaster
from models.audit import MetalAllocationAuditLog
from models.flow import MetalFlowMaster
from models.party import Party
from models.sector import FlowSector, Sector
from models.user import AppUser
from repository import audit_repo
from rules.business_rules import BusinessRules
from schemas.allocation import FlowRowInput, ReviseRowInput
from services import allocation_service
from services.allocation_service import (
    build_allocation_model,
    preview_revision,
    revise_daily_allocation,
)
from services.exceptions import (
    DateNotSavedError,
    DuplicateRequestError,
    NotAuthorizedError,
    RevisionDisabledError,
    ValidationError,
)
from services.scope_service import build_scope

# Real calendar dates: Saturday, Monday, Tuesday. The Monday rule is exercised.
FRI = date(2026, 8, 14)
SAT = date(2026, 8, 15)
MON = date(2026, 8, 17)
TUE = date(2026, 8, 18)

REASON = "Recount after the vault check."  # comfortably over ten characters


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    rc = Party(party_name="Royal Chain", party_key="royal chain")
    aj = Party(party_name="Aalishaan", party_key="aalishaan")
    session.add_all([rc, aj])
    session.flush()

    session.add_all(
        [
            Sector(
                sector_name="RC Customer Orders",
                sector_key="rc customer orders",
                party_id=rc.party_id,
                priority="Priority 1",
                purity="Any",
                display_order=1,
            ),
            Sector(
                sector_name="AJ Orders",
                sector_key="aj orders",
                party_id=aj.party_id,
                priority="Priority 2",
                purity="Any",
                display_order=2,
            ),
            FlowSector(
                sector_name="Royal Chain",
                sector_key="royal chain",
                party_id=rc.party_id,
                display_order=1,
            ),
        ]
    )
    session.commit()
    yield session
    session.close()


def _user(db, *, is_admin=True, email="admin@royalchains.com"):
    user = AppUser(
        email=email,
        display_name=email,
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


def _sectors(db):
    return {s.sector_name: s for s in db.query(Sector).order_by(Sector.display_order).all()}


def _save_day(db, day: date, figures: dict[str, tuple[int, int, int]], *, acquired=0):
    """Write one day's rows directly, the way a committed save leaves them.

    `figures` maps sector name -> (previous_g, required_g, alloted_g). Sectors
    left out are written as zeros: a saved date always holds a row for every
    defined sector, and the row-count rule enforces that on the way back in.
    """
    sectors = _sectors(db)
    for name, sector in sectors.items():
        previous, required, alloted = figures.get(name, (0, 0, 0))
        db.add(
            MetalMaster(
                allocation_date=day.isoformat(),
                sector_id=sector.sector_id,
                party_id=sector.party_id,
                priority_snapshot=sector.priority,
                purity_snapshot=sector.purity,
                previous_requirement_g=previous,
                today_required_g=required,
                alloted_g=alloted,
                balance_g=previous + required - alloted,
                revision_number=0,
                saved_by="admin@royalchains.com",
            )
        )
    flow_sector = db.query(FlowSector).first()
    db.add(
        MetalFlowMaster(
            allocation_date=day.isoformat(),
            flow_sector_id=flow_sector.flow_sector_id,
            party_id=flow_sector.party_id,
            acquired_g=acquired,
            revision_number=0,
            saved_by="admin@royalchains.com",
        )
    )
    db.commit()


def _payload(db, figures: dict[str, tuple[str, str]], *, acquired="6.000"):
    """`figures` maps sector name -> (today_required_kg, alloted_kg).

    Every defined sector is sent, zero where unnamed — the payload is rebuilt
    from the live definitions and must carry a row for each of them.
    """
    sectors = _sectors(db)
    allocations = [
        ReviseRowInput(
            sector_id=sector.sector_id,
            today_required_kg=Decimal(figures.get(name, ("0.000", "0.000"))[0]),
            alloted_kg=Decimal(figures.get(name, ("0.000", "0.000"))[1]),
        )
        for name, sector in sectors.items()
    ]
    flow_sector = db.query(FlowSector).first()
    return allocations, [
        FlowRowInput(
            flow_sector_id=flow_sector.flow_sector_id, today_acquired_kg=Decimal(acquired)
        )
    ]


def _revise(db, user, day, figures, *, reason=REASON, request_id="REQ-R1", acquired="6.000"):
    allocations, flow = _payload(db, figures, acquired=acquired)
    return revise_daily_allocation(
        db,
        user=user,
        scope=_scope(db, user),
        selected=day,
        submitted_allocations=allocations,
        submitted_flow=flow,
        revision_reason=reason,
        request_id=request_id,
    )


def _rows(db, day: date) -> dict[str, MetalMaster]:
    names = {s.sector_id: s.sector_name for s in db.query(Sector).all()}
    return {
        names[r.sector_id]: r
        for r in db.query(MetalMaster).filter_by(allocation_date=day.isoformat()).all()
    }


def _actions(db) -> list[str]:
    return [
        r.action_type
        for r in db.query(MetalAllocationAuditLog)
        .order_by(MetalAllocationAuditLog.audit_row_id)
        .all()
    ]


# --------------------------------------------------------------- the cascade


def test_the_worked_example_end_to_end(db) -> None:
    """The spec's table, through the real service and the real ledger."""
    user = _user(db)
    # Saturday's own previous requirement is derived from ITS source date, so
    # Friday has to leave a balance of 10.000 for the spec's table to hold.
    _save_day(db, FRI, {"RC Customer Orders": (0, 10_000, 0)})  # bal 10.000
    _save_day(db, SAT, {"RC Customer Orders": (10_000, 5_000, 12_000)})  # bal 3.000
    _save_day(db, MON, {"RC Customer Orders": (3_000, 4_000, 2_000)})  # bal 5.000
    _save_day(db, TUE, {"RC Customer Orders": (5_000, 1_000, 6_000)})  # bal 0.000

    result = _revise(db, user, SAT, {"RC Customer Orders": ("5.000", "8.000")})

    assert result.revision_number == 1
    assert [c.allocation_date for c in result.cascaded] == [MON, TUE]

    sat = _rows(db, SAT)["RC Customer Orders"]
    mon = _rows(db, MON)["RC Customer Orders"]
    tue = _rows(db, TUE)["RC Customer Orders"]

    # Saturday's own previous requirement is unchanged — it comes from ITS
    # source date (Friday), which nobody edited. That is precisely why the
    # Prev. Req. diff only ever shows up on the CASCADED dates.
    assert sat.previous_requirement_g == 10_000
    assert sat.alloted_g == 8_000
    assert sat.balance_g == 7_000

    assert (mon.previous_requirement_g, mon.balance_g) == (7_000, 9_000)
    assert (tue.previous_requirement_g, tue.balance_g) == (9_000, 4_000)


def test_the_cascade_never_touches_required_or_alloted(db) -> None:
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 1_000)})
    _save_day(db, MON, {"RC Customer Orders": (4_000, 7_000, 2_000)})

    _revise(db, user, SAT, {"RC Customer Orders": ("5.000", "5.000")})

    mon = _rows(db, MON)["RC Customer Orders"]
    assert mon.today_required_g == 7_000, "the cascade must not move Today's Required"
    assert mon.alloted_g == 2_000, "nor Alloted"
    assert mon.priority_snapshot == "Priority 1", "nor the historical snapshots"


def test_an_untouched_sector_gets_no_cascade_entry(db) -> None:
    """Each sector's chain is independent."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 9_000, 0), "AJ Orders": (0, 4_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (9_000, 0, 0), "AJ Orders": (4_000, 0, 0)})

    # Only RC changes; AJ keeps required 4.000 / alloted 0.
    result = _revise(
        db,
        user,
        SAT,
        {"RC Customer Orders": ("3.000", "0.000"), "AJ Orders": ("4.000", "0.000")},
    )

    assert len(result.cascaded) == 1
    assert result.cascaded[0].sectors_changed == 1
    assert _rows(db, MON)["AJ Orders"].previous_requirement_g == 4_000


def test_editing_the_latest_saved_date_cascades_nothing(db) -> None:
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 1_000)})

    result = _revise(db, user, SAT, {"RC Customer Orders": ("5.000", "2.000")})

    assert result.cascaded == []
    assert _actions(db) == ["REVISE"], "one entry, no cascade entries"


def test_a_cascade_may_drive_a_balance_negative(db) -> None:
    """Over-allocation is permitted; the revision is not blocked."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 9_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (9_000, 0, 5_000)})

    result = _revise(db, user, SAT, {"RC Customer Orders": ("0.000", "0.000")})

    assert _rows(db, MON)["RC Customer Orders"].balance_g == -5_000
    assert result.cascaded[0].negative_balance_sectors == 1


# ------------------------------------------------------------------ the audit


def test_cascade_entries_link_to_their_parent(db) -> None:
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (5_000, 0, 0)})

    result = _revise(db, user, SAT, {"RC Customer Orders": ("9.000", "0.000")})

    children = audit_repo.get_children(db, result.audit_id)
    assert [c.audit_id for c in children] == [c.audit_id for c in result.cascaded]
    assert children[0].action_type == "RECALCULATE"
    assert children[0].parent_audit_id == result.audit_id
    assert children[0].request_id == result.request_id, "the parent's request id"
    assert "Recalculated after revision of" in children[0].revision_reason


def test_the_revisions_kpi_counts_the_parent_only(db) -> None:
    """A cascade is a consequence, not an administrator edit."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (5_000, 0, 0)})
    _save_day(db, TUE, {"RC Customer Orders": (5_000, 0, 0)})

    result = _revise(db, user, SAT, {"RC Customer Orders": ("9.000", "0.000")})
    assert len(result.cascaded) == 2

    counts = audit_repo.count_by_status(db)
    assert counts["revisions"] == 1, "two RECALCULATE rows must not inflate it"


def test_every_changed_date_gets_its_own_revision_number(db) -> None:
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (5_000, 0, 0)})

    _revise(db, user, SAT, {"RC Customer Orders": ("9.000", "0.000")})

    assert _rows(db, SAT)["RC Customer Orders"].revision_number == 1
    assert _rows(db, MON)["RC Customer Orders"].revision_number == 1


def test_the_flow_ledger_is_untouched_by_the_cascade(db) -> None:
    """Metal Flow has no balance column, so it has nothing to carry forward."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)}, acquired=1_000)
    _save_day(db, MON, {"RC Customer Orders": (5_000, 0, 0)}, acquired=2_000)

    _revise(db, user, SAT, {"RC Customer Orders": ("9.000", "0.000")})

    monday_flow = (
        db.query(MetalFlowMaster).filter_by(allocation_date=MON.isoformat()).one()
    )
    assert monday_flow.acquired_g == 2_000


# ----------------------------------------------------------------- the guards


def test_an_operator_is_refused_and_the_attempt_is_audited(db) -> None:
    """The UI flag is never trusted, and a blocked attempt is recorded."""
    admin = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    operator = _user(db, is_admin=False, email="op@royalchains.com")

    with pytest.raises(NotAuthorizedError) as exc:
        _revise(db, operator, SAT, {"RC Customer Orders": ("1.000", "1.000")})

    assert exc.value.code == "NOT_AUTHORIZED"
    assert _actions(db) == ["UNAUTHORIZED_REVISION"]
    assert _rows(db, SAT)["RC Customer Orders"].today_required_g == 5_000
    assert admin is not None


def test_a_short_reason_is_refused_and_audited(db) -> None:
    """Proves the reason is enforced AND that a validation failure is audited —
    the save path used to let one escape with no record at all."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})

    with pytest.raises(ValidationError) as exc:
        _revise(db, user, SAT, {"RC Customer Orders": ("1.000", "1.000")}, reason="too short")

    assert exc.value.code == "REVISION_REASON_TOO_SHORT"
    assert _actions(db) == ["FAILED_REVISION"]


def test_an_unsaved_date_has_nothing_to_revise(db) -> None:
    user = _user(db)
    with pytest.raises(DateNotSavedError) as exc:
        _revise(db, user, SAT, {"RC Customer Orders": ("1.000", "1.000")})
    assert exc.value.code == "DATE_NOT_SAVED"
    assert _actions(db) == ["FAILED_REVISION"]


def test_revision_disabled_refuses_and_writes_no_audit(db, monkeypatch) -> None:
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    monkeypatch.setattr(
        allocation_service, "business_rules", BusinessRules(allow_admin_revision=False)
    )

    with pytest.raises(RevisionDisabledError) as exc:
        _revise(db, user, SAT, {"RC Customer Orders": ("1.000", "1.000")})

    assert exc.value.code == "REVISION_DISABLED"
    assert _actions(db) == [], "a disabled feature is not an authorisation failure"


def test_a_repeated_request_id_does_not_revise_twice(db) -> None:
    """Unlike save, there is no date_exists check to catch a double click."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (5_000, 0, 0)})

    _revise(db, user, SAT, {"RC Customer Orders": ("9.000", "0.000")}, request_id="REQ-X")
    with pytest.raises(DuplicateRequestError):
        _revise(db, user, SAT, {"RC Customer Orders": ("1.000", "0.000")}, request_id="REQ-X")

    assert _actions(db).count("REVISE") == 1
    assert _actions(db).count("RECALCULATE") == 1
    assert _rows(db, SAT)["RC Customer Orders"].revision_number == 1


# ------------------------------------------------------------------- the rest


def test_a_client_supplied_previous_requirement_is_ignored(db) -> None:
    """The revise schema has no such field, and the server derives it anyway.

    Saturday has no source date, so its previous requirement must be zero no
    matter what arrives.
    """
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (10_000, 5_000, 0)})

    _revise(db, user, SAT, {"RC Customer Orders": ("5.000", "0.000")})

    assert not hasattr(ReviseRowInput, "previous_requirement_kg")
    assert _rows(db, SAT)["RC Customer Orders"].previous_requirement_g == 0


def test_a_failure_mid_cascade_rolls_back_every_date(db, monkeypatch) -> None:
    """ATOMICITY. The ledger and the log must look exactly as they did."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (5_000, 0, 0)})
    _save_day(db, TUE, {"RC Customer Orders": (5_000, 0, 0)})

    calls = {"n": 0}
    real = allocation_service.allocation_repo.apply_recalculation

    def explode(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk gave out mid-cascade")
        return real(*args, **kwargs)

    monkeypatch.setattr(
        allocation_service.allocation_repo, "apply_recalculation", explode
    )

    with pytest.raises(Exception):
        _revise(db, user, SAT, {"RC Customer Orders": ("9.000", "0.000")})

    # Nothing moved — not the edited date, not the first cascaded date.
    assert _rows(db, SAT)["RC Customer Orders"].today_required_g == 5_000
    assert _rows(db, MON)["RC Customer Orders"].previous_requirement_g == 5_000
    assert _rows(db, TUE)["RC Customer Orders"].previous_requirement_g == 5_000

    actions = _actions(db)
    assert actions == ["FAILED_REVISION"], "no REVISE, no RECALCULATE, just the failure"


def test_the_screen_agrees_with_the_cascade_afterwards(db) -> None:
    """The headline invariant: the Daily Allocation screen and the ledger must
    show the same figures, because both go through one source-date rule."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 1_000)})
    _save_day(db, MON, {"RC Customer Orders": (4_000, 2_000, 0)})

    _revise(db, user, SAT, {"RC Customer Orders": ("9.000", "1.000")})

    stored = _rows(db, MON)["RC Customer Orders"]
    model = build_allocation_model(db, MON, _scope(db, user))
    shown = next(r for r in model.allocations if r.sector_name == "RC Customer Orders")

    assert shown.previous_requirement_g == stored.previous_requirement_g == 8_000
    assert shown.balance_g == stored.balance_g


# ---------------------------------------------------------------- the preview


def test_the_preview_matches_what_the_commit_does(db) -> None:
    """Otherwise the dialog can promise one thing and the commit do another."""
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (5_000, 0, 0)})
    _save_day(db, TUE, {"RC Customer Orders": (5_000, 0, 0)})

    allocations, flow = _payload(db, {"RC Customer Orders": ("9.000", "0.000")})
    preview = preview_revision(
        db,
        user=user,
        scope=_scope(db, user),
        selected=SAT,
        submitted_allocations=allocations,
        submitted_flow=flow,
        revision_reason=REASON,
    )

    result = _revise(db, user, SAT, {"RC Customer Orders": ("9.000", "0.000")})

    assert preview.date_count == len(result.cascaded)
    assert preview.sector_count == 1


def test_the_preview_writes_nothing(db) -> None:
    user = _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    _save_day(db, MON, {"RC Customer Orders": (5_000, 0, 0)})

    allocations, flow = _payload(db, {"RC Customer Orders": ("9.000", "0.000")})
    preview_revision(
        db,
        user=user,
        scope=_scope(db, user),
        selected=SAT,
        submitted_allocations=allocations,
        submitted_flow=flow,
        revision_reason=REASON,
    )

    assert _actions(db) == [], "a preview is a read"
    assert _rows(db, MON)["RC Customer Orders"].previous_requirement_g == 5_000


def test_the_preview_refuses_an_operator_without_auditing(db) -> None:
    """Auditing rejected previews would let anyone flood the log by clicking."""
    _user(db)
    _save_day(db, SAT, {"RC Customer Orders": (0, 5_000, 0)})
    operator = _user(db, is_admin=False, email="op@royalchains.com")

    allocations, flow = _payload(db, {"RC Customer Orders": ("9.000", "0.000")})
    with pytest.raises(NotAuthorizedError):
        preview_revision(
            db,
            user=operator,
            scope=_scope(db, operator),
            selected=SAT,
            submitted_allocations=allocations,
            submitted_flow=flow,
            revision_reason=REASON,
        )

    assert _actions(db) == []
