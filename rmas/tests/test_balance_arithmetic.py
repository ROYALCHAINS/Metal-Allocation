"""tests/test_balance_arithmetic.py — the one equation the system exists to evaluate.

    balance = previous_requirement + today_required - alloted

Plus the weight assertions and the four togglable save rules, ported from
ValidationService.gs.
"""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from rules.business_rules import BusinessRules
from services.exceptions import ValidationError
from services.validation_service import (
    Totals,
    assert_revision_reason,
    assert_save_rules,
    assert_signed_weight,
    assert_valid_weight,
    compute_balance_g,
    compute_totals,
    nearly_equal_g,
)
from services.weight_service import kg_to_grams


@dataclass
class _Alloc:
    previous_requirement_g: int
    today_required_g: int
    alloted_g: int
    balance_g: int


@dataclass
class _Flow:
    today_acquired_g: int


def _kg(value: str) -> int:
    return kg_to_grams(Decimal(value))


# ----------------------------------------------------------------- the equation


@pytest.mark.parametrize(
    "previous, required, alloted, expected",
    [
        ("0", "0", "0", "0.000"),
        ("0", "10", "4", "6.000"),
        ("100", "10", "30", "80.000"),
        # Allocating more than required is legitimate; the negative carries.
        ("0", "5", "8", "-3.000"),
        ("-3", "5", "0", "2.000"),
        # A zero closing balance is valid and expected, not an edge case.
        ("0", "7.5", "7.5", "0.000"),
        ("0.001", "0.001", "0.001", "0.001"),
    ],
)
def test_balance_equation(previous: str, required: str, alloted: str, expected: str) -> None:
    result = compute_balance_g(_kg(previous), _kg(required), _kg(alloted))
    assert result == _kg(expected)


def test_balance_is_exact_at_three_decimals() -> None:
    """The classic float trap: 0.1 + 0.2 - 0.3 must be exactly zero."""
    assert compute_balance_g(_kg("0.1"), _kg("0.2"), _kg("0.3")) == 0


# --------------------------------------------------------------- weight guards


def test_signed_weight_allows_negative() -> None:
    """Previous Requirement and Balance carry a prior negative balance."""
    assert assert_signed_weight(Decimal("-3.5"), "Previous Requirement") == _kg("-3.5")


def test_valid_weight_rejects_negative() -> None:
    """Inputs may not be negative, unlike derived values."""
    with pytest.raises(ValidationError) as exc:
        assert_valid_weight(Decimal("-0.001"), "Alloted")
    assert exc.value.code == "NEGATIVE_VALUE"


@pytest.mark.parametrize("empty", [None, ""])
def test_blank_weight_is_zero(empty) -> None:
    assert assert_valid_weight(empty, "Alloted") == 0


def test_commas_are_stripped() -> None:
    """The sheet and the browser both produce '1,234.500'."""
    assert assert_valid_weight("1,234.500", "Alloted") == _kg("1234.5")


def test_garbage_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        assert_valid_weight("not a number", "Alloted")
    assert exc.value.code == "INVALID_NUMBER"


def test_float_is_rejected() -> None:
    """Accepting a float would reintroduce the drift grams exist to prevent."""
    with pytest.raises(ValidationError) as exc:
        assert_valid_weight(1.005, "Alloted")
    assert exc.value.code == "INVALID_NUMBER"


@pytest.mark.parametrize("assertion", [assert_valid_weight, assert_signed_weight])
def test_max_weight_ceiling_enforced(assertion) -> None:
    assert assertion(Decimal("100000"), "Alloted") == _kg("100000")
    with pytest.raises(ValidationError) as exc:
        assertion(Decimal("100000.001"), "Alloted")
    assert exc.value.code == "VALUE_TOO_LARGE"


def test_signed_weight_ceiling_applies_to_magnitude() -> None:
    with pytest.raises(ValidationError):
        assert_signed_weight(Decimal("-100000.001"), "Previous Requirement")


# --------------------------------------------------------------------- totals


def test_compute_totals() -> None:
    allocations = [
        _Alloc(_kg("10"), _kg("5"), _kg("3"), _kg("12")),
        _Alloc(_kg("0"), _kg("2.5"), _kg("2.5"), _kg("0")),
    ]
    flows = [_Flow(_kg("4")), _Flow(_kg("1.5"))]

    totals = compute_totals(allocations, flows)

    assert totals.total_previous_requirement_g == _kg("10")
    assert totals.total_today_required_g == _kg("7.5")
    assert totals.total_alloted_g == _kg("5.5")
    assert totals.total_balance_g == _kg("12")
    assert totals.total_acquired_g == _kg("5.5")
    assert totals.remaining_to_allocate_g == 0


def test_remaining_to_allocate_clamps_at_zero() -> None:
    """Over-allocating leaves nothing 'remaining', it does not go negative."""
    totals = compute_totals([_Alloc(0, 0, _kg("10"), 0)], [_Flow(_kg("4"))])
    assert totals.remaining_to_allocate_g == 0


def test_nearly_equal_is_exact_in_grams() -> None:
    """Legacy's 0.0005 epsilon only ever matched identical 3-decimal values, so
    in exact grams this is plain equality — a 1-gram difference is NOT equal."""
    assert nearly_equal_g(_kg("1.000"), _kg("1.000")) is True
    assert nearly_equal_g(_kg("1.000"), _kg("1.001")) is False


# ----------------------------------------------------------------- save rules


def _totals(*, acquired: str = "0", alloted: str = "0") -> Totals:
    return Totals(
        total_previous_requirement_g=0,
        total_today_required_g=0,
        total_alloted_g=_kg(alloted),
        total_balance_g=0,
        total_acquired_g=_kg(acquired),
        remaining_to_allocate_g=max(0, _kg(acquired) - _kg(alloted)),
    )


def test_acquired_must_be_positive() -> None:
    """The one save rule that is enabled."""
    with pytest.raises(ValidationError) as exc:
        assert_save_rules(_totals(acquired="0", alloted="5"))
    assert exc.value.code == "NO_ACQUIRED_METAL"


def test_partial_allocation_is_allowed() -> None:
    """REQUIRE_FULL_ALLOCATION is off: alloted need not equal acquired."""
    assert_save_rules(_totals(acquired="10", alloted="4"))


def test_over_allocation_is_allowed() -> None:
    """BLOCK_OVER_ALLOCATION is off: alloted may exceed acquired."""
    assert_save_rules(_totals(acquired="4", alloted="10"))


def test_zero_alloted_is_allowed() -> None:
    """REQUIRE_POSITIVE_ALLOTED is off: a zero allotment is permitted."""
    assert_save_rules(_totals(acquired="10", alloted="0"))


def test_disabled_rules_fire_when_switched_on(monkeypatch) -> None:
    """Proves the toggles are wired, without enabling them in production —
    they are disabled by business decision (CLAUDE.md section 6)."""
    import services.validation_service as vs

    monkeypatch.setattr(vs, "business_rules", BusinessRules(require_full_allocation=True))
    with pytest.raises(ValidationError) as exc:
        vs.assert_save_rules(_totals(acquired="10", alloted="4"))
    assert exc.value.code == "INCOMPLETE_ALLOCATION"

    monkeypatch.setattr(vs, "business_rules", BusinessRules(block_over_allocation=True))
    with pytest.raises(ValidationError) as exc:
        vs.assert_save_rules(_totals(acquired="4", alloted="10"))
    assert exc.value.code == "OVER_ALLOCATED"


# ------------------------------------------------------------ revision reason


def test_revision_reason_required() -> None:
    with pytest.raises(ValidationError) as exc:
        assert_revision_reason("")
    assert exc.value.code == "REVISION_REASON_REQUIRED"


def test_revision_reason_minimum_length_is_ten() -> None:
    with pytest.raises(ValidationError) as exc:
        assert_revision_reason("too short")  # 9 characters
    assert exc.value.code == "REVISION_REASON_TOO_SHORT"

    assert assert_revision_reason("just enough") == "just enough"  # 11


def test_revision_reason_truncated_at_1000() -> None:
    assert len(assert_revision_reason("x" * 5000)) == 1000
