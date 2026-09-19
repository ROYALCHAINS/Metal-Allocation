"""
Tests for validation_service.py: Decimal rounding (ROUND_HALF_UP), the
0.0005 epsilon comparison, MAX_WEIGHT_KG ceiling, and signed-vs-unsigned
weight validation. No DB required.
"""

from decimal import Decimal

import pytest

from rmas.services.exceptions import ValidationError
from rmas.services.validation_service import (
    assert_signed_weight,
    assert_valid_weight,
    fmt3,
    nearly_equal,
    normalize_sector_key,
    round3,
    to_number,
)


def test_round3_uses_round_half_up():
    assert round3(Decimal("1.2345")) == Decimal("1.235")  # half-up, not banker's rounding
    assert round3(Decimal("1.2344")) == Decimal("1.234")
    # CLAUDE.md mandates ROUND_HALF_UP for the port (ties away from zero).
    # Note this differs from legacy's JS Math.round, whose ties go toward
    # +Infinity regardless of sign (Math.round(-1.5) === -1, not -2) — a
    # genuine, narrow behavioural difference at exact tie values on negative
    # (signed) weights, accepted per CLAUDE.md's explicit rule for the new
    # system rather than silently replicated from the legacy float quirk.
    assert round3(Decimal("-1.2345")) == Decimal("-1.235")


def test_round3_none_and_blank_are_zero():
    assert round3(None) == Decimal("0.000")
    assert round3("") == Decimal("0.000")


def test_fmt3_always_three_decimals():
    assert fmt3(Decimal("5")) == "5.000"
    assert fmt3(Decimal("5.1")) == "5.100"


def test_nearly_equal_epsilon_boundary():
    # exactly at 0.0005 is NOT nearly equal (strict less-than)
    assert not nearly_equal(Decimal("1.000"), Decimal("1.0005"))
    assert nearly_equal(Decimal("1.000"), Decimal("1.0004"))


def test_to_number_strips_thousands_commas():
    assert to_number("1,234.5") == Decimal("1234.500")


def test_normalize_sector_key_collapses_whitespace_and_dashes():
    assert normalize_sector_key("  Sector   Name ") == "sector name"
    assert normalize_sector_key("Sector–Name") == "sector-name"  # en dash -> hyphen


def test_normalize_sector_key_empty():
    assert normalize_sector_key(None) == ""
    assert normalize_sector_key("") == ""


def test_assert_valid_weight_rejects_negative():
    with pytest.raises(ValidationError) as exc:
        assert_valid_weight(Decimal("-1"), "Today's Required")
    assert exc.value.code == "NEGATIVE_VALUE"


def test_assert_valid_weight_rejects_over_max():
    with pytest.raises(ValidationError) as exc:
        assert_valid_weight(Decimal("100001"), "Alloted")
    assert exc.value.code == "VALUE_TOO_LARGE"


def test_assert_signed_weight_allows_negative_balance_carry_forward():
    assert assert_signed_weight(Decimal("-42.5"), "Previous Requirement") == Decimal("-42.500")


def test_assert_signed_weight_rejects_over_max_magnitude_either_sign():
    with pytest.raises(ValidationError):
        assert_signed_weight(Decimal("-100001"), "Previous Requirement")


def test_assert_valid_weight_invalid_number():
    with pytest.raises(ValidationError) as exc:
        assert_valid_weight("not-a-number", "Alloted")
    assert exc.value.code == "INVALID_NUMBER"
