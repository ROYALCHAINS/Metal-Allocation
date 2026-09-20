"""
services/weight_service.py
Royal Metal Allocation System — Python port

The only place kilograms become grams or vice versa.

Weights are stored as INTEGER GRAMS (schema.sql design note). The legacy system
worked in kilograms to exactly 3 decimals, and 3 decimals of a kilogram is
precisely 1 gram, so the representation is lossless — unlike SQLite REAL, which
is binary floating point and drifts.

Everything above the database speaks `Decimal` kilograms; everything at or below
it speaks `int` grams. `float` appears nowhere in this module, deliberately
(CLAUDE.md section 6, rule 1).

Ports the numeric helpers from ValidationService.gs — round3_(), toNumber_(),
nearlyEqual_() — which is why the epsilon lives here too.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from rules.business_rules import DECIMALS, EPSILON, MAX_WEIGHT_KG

_GRAMS_PER_KG = Decimal(1000)
_QUANT = Decimal(1).scaleb(-DECIMALS)  # Decimal('0.001')


def round_kg(value: Decimal) -> Decimal:
    """Round to exactly 3 decimals with ROUND_HALF_UP — legacy's round3_()."""
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


def to_decimal(value: Decimal | int | str) -> Decimal:
    """Coerce an inbound value to Decimal without ever passing through float.

    Ports ValidationService.gs's toNumber_(). A float argument is rejected
    rather than silently converted: accepting one would reintroduce exactly the
    drift this module exists to prevent.
    """
    if isinstance(value, float):
        raise TypeError("float is not accepted for weights — pass Decimal, int or str")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Not a valid weight: {value!r}") from exc


def kg_to_grams(kilograms: Decimal | int | str) -> int:
    """Convert kilograms to the integer grams actually stored."""
    return int(round_kg(to_decimal(kilograms)) * _GRAMS_PER_KG)


def grams_to_kg(grams: int) -> Decimal:
    """Convert stored integer grams back to Decimal kilograms. Always exact."""
    return (Decimal(grams) / _GRAMS_PER_KG).quantize(_QUANT)


def nearly_equal(left: Decimal, right: Decimal) -> bool:
    """Epsilon comparison — never compare weights with == (rule 2)."""
    return abs(left - right) < EPSILON


def is_within_max(kilograms: Decimal) -> bool:
    """MAX_WEIGHT_KG is a sanity ceiling on any single numeric input (rule 3)."""
    return abs(kilograms) <= MAX_WEIGHT_KG
