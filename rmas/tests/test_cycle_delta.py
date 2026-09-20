"""tests/test_cycle_delta.py — the shared newer-half-vs-older-half comparison.

Used by both the Analysis Dashboard's "Total Acquired" card and Metal Flow
History's. Pins the four edge cases of renderCycleDelta() that a naive
"compare the two halves" implementation gets wrong: the odd-count split, the
below-four-dates floor, the division by zero, and the fact that the split is by
DATE not by volume.
"""

from services.report_service import cycle_delta


def test_even_split_compares_newer_half_against_older() -> None:
    cycle = cycle_delta(
        {
            "2026-09-01": 1_000,
            "2026-09-02": 1_000,
            "2026-09-03": 1_500,
            "2026-09-04": 1_500,
        }
    )
    assert cycle.previous_g == 2_000
    assert cycle.current_g == 3_000
    assert cycle.day_count == 2
    assert cycle.change_percent == 50.0


def test_odd_count_gives_the_extra_date_to_the_current_half() -> None:
    """Five dates split 2 older / 3 newer, never 3 / 2."""
    cycle = cycle_delta({f"2026-09-0{n}": 1_000 for n in range(1, 6)})
    assert cycle.day_count == 3
    assert cycle.previous_g == 2_000
    assert cycle.current_g == 3_000


def test_fewer_than_four_dates_has_no_change() -> None:
    """Two or three dates is not a cycle — comparing them would be noise."""
    cycle = cycle_delta({"2026-09-01": 1_000, "2026-09-02": 5_000, "2026-09-03": 9_000})
    assert cycle.change_percent is None
    assert cycle.current_g == 14_000


def test_zero_older_half_has_no_change_rather_than_infinity() -> None:
    cycle = cycle_delta(
        {
            "2026-09-01": 0,
            "2026-09-02": 0,
            "2026-09-03": 4_000,
            "2026-09-04": 4_000,
        }
    )
    assert cycle.change_percent is None


def test_empty_range_is_zero_not_an_error() -> None:
    cycle = cycle_delta({})
    assert cycle.day_count == 0
    assert cycle.change_percent is None
    assert cycle.current_g == 0


def test_split_is_by_date_not_by_volume() -> None:
    """One heavy older date does not drag dates across the midpoint."""
    cycle = cycle_delta(
        {
            "2026-09-01": 900_000,
            "2026-09-02": 1,
            "2026-09-03": 1,
            "2026-09-04": 1,
        }
    )
    assert cycle.day_count == 2
    assert cycle.previous_g == 900_001
