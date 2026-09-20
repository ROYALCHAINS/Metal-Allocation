"""tests/test_weight_service.py — the integer-grams precision guarantee.

CLAUDE.md section 6, rule 1 requires this to be proven, not assumed: weights are
stored as INTEGER grams precisely so SQLite's lack of an exact decimal type
cannot introduce drift. These tests are the proof.
"""

from decimal import Decimal

import pytest

from services.weight_service import (
    grams_to_kg,
    is_within_max,
    kg_to_grams,
    nearly_equal,
    round_kg,
    to_decimal,
)


@pytest.mark.parametrize(
    "kilograms, expected_grams",
    [
        ("0", 0),
        ("1", 1000),
        ("0.001", 1),
        ("12.345", 12345),
        ("100000", 100_000_000),
        ("-5.250", -5250),
        # The classic binary-float traps: 0.1 + 0.2 territory.
        ("0.1", 100),
        ("0.3", 300),
        ("1.005", 1005),
        ("2.675", 2675),
    ],
)
def test_kg_to_grams_is_exact(kilograms: str, expected_grams: int) -> None:
    assert kg_to_grams(Decimal(kilograms)) == expected_grams


@pytest.mark.parametrize(
    "kilograms",
    ["0", "0.001", "12.345", "999.999", "100000", "-5.250", "0.1", "1.005", "2.675"],
)
def test_round_trip_is_lossless(kilograms: str) -> None:
    """kg -> grams -> kg must return EXACTLY the original value."""
    original = Decimal(kilograms)
    assert grams_to_kg(kg_to_grams(original)) == original


def test_accumulated_round_trips_do_not_drift() -> None:
    """A float-backed store would drift here; integer grams cannot."""
    total_g = 0
    for _ in range(1000):
        total_g += kg_to_grams(Decimal("0.001"))
    assert total_g == 1000
    assert grams_to_kg(total_g) == Decimal("1.000")


def test_round_half_up_at_the_third_decimal() -> None:
    """ROUND_HALF_UP, not banker's rounding — legacy's round3_()."""
    assert round_kg(Decimal("0.0005")) == Decimal("0.001")
    assert round_kg(Decimal("0.0015")) == Decimal("0.002")  # banker's would give 0.002
    assert round_kg(Decimal("0.0025")) == Decimal("0.003")  # banker's would give 0.002
    assert round_kg(Decimal("0.0004")) == Decimal("0.000")


def test_float_input_is_rejected() -> None:
    """Accepting a float would reintroduce exactly the drift this prevents."""
    with pytest.raises(TypeError):
        to_decimal(1.005)
    with pytest.raises(TypeError):
        kg_to_grams(1.005)


def test_nearly_equal_uses_the_legacy_epsilon() -> None:
    """Epsilon is 0.0005 — half of the third decimal place."""
    assert nearly_equal(Decimal("1.0000"), Decimal("1.0004")) is True
    assert nearly_equal(Decimal("1.0000"), Decimal("1.0005")) is False
    assert nearly_equal(Decimal("1.000"), Decimal("1.000")) is True


def test_max_weight_ceiling() -> None:
    assert is_within_max(Decimal("100000")) is True
    assert is_within_max(Decimal("100000.001")) is False
    assert is_within_max(Decimal("-100000")) is True
