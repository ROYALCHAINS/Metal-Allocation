"""tests/test_cascade_service.py — the forward cascade arithmetic.

Pure functions, no database. The cascade decides what every later saved date's
previous_requirement and balance become after an earlier date is revised, so
the arithmetic is worth pinning exhaustively and cheaply.

Dates below are real: 2026-08-15 is a Saturday, 08-17 a Monday, 08-18 a Tuesday.
The Monday rule (look back two days, to Saturday) is load-bearing in several of
these and would silently pass with arbitrary dates.
"""

from datetime import date, timedelta

import pytest

from rules.business_rules import BusinessRules
from services import date_service
from services.cascade_service import DateLedger, LedgerRow, cascade_forward

SAT = "2026-08-15"
SUN = "2026-08-16"
MON = "2026-08-17"
TUE = "2026-08-18"

A = 1  # sector ids
B = 2


def _row(sector_id, previous, required, alloted):
    """A row whose stored balance is self-consistent with its own figures."""
    return LedgerRow(
        sector_id=sector_id,
        previous_requirement_g=previous,
        today_required_g=required,
        alloted_g=alloted,
        balance_g=previous + required - alloted,
    )


def test_the_worked_example_from_the_spec() -> None:
    """Saturday's Alloted drops 12.000 -> 8.000, so its balance 3.000 -> 7.000.

    The spec's table: Monday's Prev. Req. moves 3 -> 7 and Tuesday's 5 -> 9.
    Saturday's own Prev. Req. is untouched, which is exactly why the cascade
    entries are needed for the audit log to show a Prev. Req. change at all.
    """
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 10_000, 5_000, 8_000)],  # balance now 7.000
        later_ledgers=[
            DateLedger(MON, (_row(A, 3_000, 4_000, 2_000),)),  # was 5.000
            DateLedger(TUE, (_row(A, 5_000, 1_000, 6_000),)),  # was 0.000
        ],
        saved_dates=[SAT, MON, TUE],
    )

    assert [r.allocation_date for r in result.recalculated] == [MON, TUE]

    monday = result.recalculated[0].changes[0]
    assert (monday.before_previous_requirement_g, monday.previous_requirement_g) == (
        3_000,
        7_000,
    )
    assert (monday.before_balance_g, monday.balance_g) == (5_000, 9_000)

    tuesday = result.recalculated[1].changes[0]
    assert (tuesday.before_previous_requirement_g, tuesday.previous_requirement_g) == (
        5_000,
        9_000,
    )
    assert (tuesday.before_balance_g, tuesday.balance_g) == (0, 4_000)


def test_monday_sources_saturday_and_tuesday_sources_monday() -> None:
    """The six-day week, in the cascade as on the screen."""
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 0, 0)],
        later_ledgers=[
            DateLedger(MON, (_row(A, 9_000, 0, 0),)),
            DateLedger(TUE, (_row(A, 9_000, 0, 0),)),
        ],
        saved_dates=[SAT, MON, TUE],
    )
    assert result.recalculated[0].source_date == SAT, "Monday looks back to Saturday"
    assert result.recalculated[1].source_date == MON


def test_a_gap_falls_back_to_the_latest_saved_date() -> None:
    """A skipped day must never silently reset a balance to zero."""
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 6_000, 0)],  # balance 6.000
        later_ledgers=[DateLedger(TUE, (_row(A, 0, 0, 0),))],
        saved_dates=[SAT, TUE],  # Monday never saved
    )
    # Tuesday's rule date is Monday, which has no rows, so it falls back.
    assert result.recalculated[0].source_date == SAT
    assert result.recalculated[0].changes[0].previous_requirement_g == 6_000


def test_the_fallback_can_land_later_than_the_rule_date() -> None:
    """Legacy searches for the latest saved date before SELECTED, not before the
    rule date — so a Monday whose Saturday is empty can source from Sunday."""
    result = cascade_forward(
        edited_date=SUN,
        edited_rows=[_row(A, 0, 4_000, 0)],  # Sunday balance 4.000
        later_ledgers=[DateLedger(MON, (_row(A, 0, 0, 0),))],
        saved_dates=[SUN, MON],  # Saturday absent
    )
    assert result.recalculated[0].source_date == SUN, "later than Monday's rule date"
    assert result.recalculated[0].changes[0].previous_requirement_g == 4_000


def test_a_sector_absent_on_its_source_date_carries_zero() -> None:
    """Zero, never the value from some earlier date."""
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 5_000, 0)],  # only sector A on Saturday
        later_ledgers=[DateLedger(MON, (_row(B, 7_000, 0, 0),))],
        saved_dates=[SAT, MON],
    )
    change = result.recalculated[0].changes[0]
    assert change.sector_id == B
    assert change.previous_requirement_g == 0
    assert change.balance_g == 0


def test_a_negative_balance_is_reported_and_never_blocked() -> None:
    """Over-allocation is permitted, so the cascade records it and carries on."""
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 0, 0)],  # Saturday balance now 0
        later_ledgers=[DateLedger(MON, (_row(A, 8_000, 0, 3_000),))],
        saved_dates=[SAT, MON],
    )
    entry = result.recalculated[0]
    assert entry.changes[0].balance_g == -3_000
    assert entry.negative_balance_sector_ids == (A,)
    assert result.negative_balance_dates == (MON,)


def test_an_untouched_sector_produces_no_change() -> None:
    """Each sector's chain is independent."""
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 9_000, 0), _row(B, 0, 4_000, 0)],
        later_ledgers=[
            DateLedger(MON, (_row(A, 1_000, 0, 0), _row(B, 4_000, 0, 0))),
        ],
        saved_dates=[SAT, MON],
    )
    changed = {c.sector_id for c in result.recalculated[0].changes}
    assert changed == {A}, "B already carried 4.000 and is unchanged"
    assert result.sector_count == 1


def test_editing_the_latest_saved_date_cascades_nothing() -> None:
    result = cascade_forward(
        edited_date=TUE,
        edited_rows=[_row(A, 1_000, 1_000, 1_000)],
        later_ledgers=[],
        saved_dates=[SAT, MON, TUE],
    )
    assert result.recalculated == ()
    assert result.examined_date_count == 0


def test_a_date_whose_source_did_not_move_is_skipped() -> None:
    """propagate_only: a revision must not claim credit for corrections it did
    not cause. Unrelated drift is left for the reconciliation report."""
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 0, 0)],  # Saturday balance unchanged at 0
        later_ledgers=[
            DateLedger(MON, (_row(A, 0, 0, 0),)),  # already consistent
            DateLedger(TUE, (_row(A, 999, 0, 0),)),  # stale, but not ours to fix
        ],
        saved_dates=[SAT, MON, TUE],
    )
    assert result.recalculated == ()
    assert result.skipped_date_count == 1, "Tuesday skipped: Monday never moved"


def test_propagate_off_recomputes_everything() -> None:
    """The reconciliation script's mode: same arithmetic, no skipping."""
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 0, 0)],
        later_ledgers=[
            DateLedger(MON, (_row(A, 0, 0, 0),)),
            DateLedger(TUE, (_row(A, 999, 0, 0),)),  # stale
        ],
        saved_dates=[SAT, MON, TUE],
        propagate_only=False,
    )
    assert [r.allocation_date for r in result.recalculated] == [TUE]
    assert result.recalculated[0].changes[0].previous_requirement_g == 0


def test_the_cascade_never_touches_required_alloted_or_the_sector_set() -> None:
    """Only previous_requirement and balance may move."""
    before = (_row(A, 1_000, 7_000, 2_000), _row(B, 3_000, 5_000, 9_000))
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 50_000, 0), _row(B, 0, 50_000, 0)],
        later_ledgers=[DateLedger(MON, before)],
        saved_dates=[SAT, MON],
    )
    after = result.recalculated[0].rows_after
    assert [r.sector_id for r in after] == [A, B]
    for original, updated in zip(before, after, strict=True):
        assert updated.today_required_g == original.today_required_g
        assert updated.alloted_g == original.alloted_g


def test_the_balance_formula_holds_on_every_recalculated_row() -> None:
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 12_345, 0)],
        later_ledgers=[
            DateLedger(MON, (_row(A, 0, 6_000, 1_000),)),
            DateLedger(TUE, (_row(A, 0, 500, 9_000),)),
        ],
        saved_dates=[SAT, MON, TUE],
    )
    for entry in result.recalculated:
        for row in entry.rows_after:
            assert row.balance_g == (
                row.previous_requirement_g + row.today_required_g - row.alloted_g
            )


def test_carry_forward_disabled_breaks_the_chain_at_a_gap(monkeypatch) -> None:
    """With the toggle off, a missing rule date has no fallback — so the chain
    stops there and the revision cannot reach past it.

    Under propagate_only that means the later date is left alone entirely: its
    stored figure is stale relative to "no source", but that is pre-existing
    drift, not something this edit caused. The reconciliation report is what
    surfaces it.

    Patches the name in the module that READS it — date_service owns the rule —
    following the pattern in test_balance_arithmetic.py.
    """
    monkeypatch.setattr(
        date_service,
        "business_rules",
        BusinessRules(carry_forward_from_latest_saved=False),
    )
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 6_000, 0)],
        later_ledgers=[DateLedger(TUE, (_row(A, 6_000, 0, 0),))],
        saved_dates=[SAT, TUE],  # Monday, Tuesday's rule date, is missing
    )
    assert result.recalculated == ()
    assert result.skipped_date_count == 1


def test_carry_forward_disabled_zeroes_the_gap_under_full_recompute(monkeypatch) -> None:
    """The same configuration seen by the reconciliation report: no source date
    at all, so the carried figure is zero rather than an older balance."""
    monkeypatch.setattr(
        date_service,
        "business_rules",
        BusinessRules(carry_forward_from_latest_saved=False),
    )
    result = cascade_forward(
        edited_date=SAT,
        edited_rows=[_row(A, 0, 6_000, 0)],
        later_ledgers=[DateLedger(TUE, (_row(A, 6_000, 0, 0),))],
        saved_dates=[SAT, TUE],
        propagate_only=False,
    )
    assert result.recalculated[0].source_date is None
    assert result.recalculated[0].changes[0].previous_requirement_g == 0


@pytest.mark.parametrize("count", [1, 5, 40])
def test_examined_count_matches_the_dates_supplied(count) -> None:
    """Real calendar dates, so month lengths cannot make the test lie."""
    start = date(2026, 9, 1)
    ledgers = [
        DateLedger((start + timedelta(days=offset)).isoformat(), (_row(A, 0, 0, 0),))
        for offset in range(count)
    ]
    edited = (start - timedelta(days=1)).isoformat()
    result = cascade_forward(
        edited_date=edited,
        edited_rows=[_row(A, 0, 0, 0)],
        later_ledgers=ledgers,
        saved_dates=[edited, *[dl.allocation_date for dl in ledgers]],
    )
    assert result.examined_date_count == count
