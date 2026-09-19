"""
validation_service.py
Royal Metal Allocation System — Python port

Ports ValidationService.gs's numeric helpers. Weights are Decimal end to end
(CLAUDE.md critical rule #1) and rounded with ROUND_HALF_UP at every
persistence boundary (#2). EPSILON (0.0005) is the only permitted way to
compare two weights — never `==` (#2). MAX_WEIGHT_KG (100000) bounds every
single numeric input (#3).
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Protocol

from rmas.config import get_settings
from rmas.rules.business_rules import BusinessRules
from rmas.services.exceptions import ValidationError

_settings = get_settings()
_QUANT = Decimal(10) ** -_settings.weight_decimals  # Decimal('0.001')

_DASH_VARIANTS = re.compile("[‐-―−]")
_WHITESPACE = re.compile(r"\s+")


def round3(value: Decimal | int | float | str | None) -> Decimal:
    """Legacy round3_(). Non-numeric or None -> Decimal('0.000')."""
    if value is None or value == "":
        return Decimal("0.000")
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        return Decimal("0.000")
    return d.quantize(_QUANT, rounding=ROUND_HALF_UP)


def to_number(value: Decimal | int | float | str | None) -> Decimal:
    """Legacy toNumber_() — parses a raw cell/input value, stripping thousands commas."""
    if value is None or value == "":
        return Decimal("0.000")
    if isinstance(value, Decimal):
        return round3(value)
    s = str(value).replace(",", "").strip()
    if not s:
        return Decimal("0.000")
    try:
        return round3(Decimal(s))
    except InvalidOperation:
        return Decimal("0.000")


def fmt3(value: Decimal) -> str:
    """Legacy fmt3_() — fixed 3-decimal string for display."""
    return f"{round3(value):.3f}"


def nearly_equal(a: Decimal, b: Decimal) -> bool:
    """Legacy nearlyEqual_() — the ONLY sanctioned way to compare two weights."""
    return abs(round3(a) - round3(b)) < _settings.weight_epsilon


def normalize_sector_key(name: str | None) -> str:
    """
    Legacy normalizeSectorKey_(). Never match a sector/party on row position —
    always on this normalized key: dash variants -> hyphen, collapsed
    whitespace, trimmed, lowercased.
    """
    if not name:
        return ""
    s = _DASH_VARIANTS.sub("-", str(name))
    s = _WHITESPACE.sub(" ", s).strip()
    return s.lower()


def assert_signed_weight(value: Decimal | int | float | str | None, label: str) -> Decimal:
    """
    Legacy assertSignedWeight_(). For DERIVED weights allowed to be negative
    (previous_requirement, balance) — an allocation may exceed the
    requirement, so the resulting balance can be negative and legitimately
    carries into the next day. Only the magnitude is sanity-checked.
    """
    raw = _parse_raw(value, label)
    if abs(raw) > _settings.max_weight_kg:
        raise ValidationError(f"{label} exceeds the maximum permitted weight.", code="VALUE_TOO_LARGE")
    return round3(raw)


def assert_valid_weight(value: Decimal | int | float | str | None, label: str) -> Decimal:
    """Legacy assertValidWeight_(). For INPUT weights — may not be negative."""
    raw = _parse_raw(value, label)
    if raw < 0:
        raise ValidationError(f"{label} cannot be negative.", code="NEGATIVE_VALUE")
    if raw > _settings.max_weight_kg:
        raise ValidationError(f"{label} exceeds the maximum permitted weight.", code="VALUE_TOO_LARGE")
    return round3(raw)


def _parse_raw(value: Decimal | int | float | str | None, label: str) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    s = str(value).replace(",", "").strip() if not isinstance(value, Decimal) else value
    try:
        return Decimal(s) if not isinstance(s, Decimal) else s
    except InvalidOperation as exc:
        raise ValidationError(f"{label} must be a valid number.", code="INVALID_NUMBER") from exc


class _HasAllocationFields(Protocol):
    previous_requirement: Decimal
    today_required: Decimal
    alloted: Decimal
    balance: Decimal


class _HasAcquiredField(Protocol):
    today_acquired: Decimal


@dataclass
class Totals:
    """Legacy computeTotals_()'s return shape."""

    total_previous_requirement: Decimal
    total_today_required: Decimal
    total_alloted: Decimal
    total_balance: Decimal
    total_acquired: Decimal
    remaining_to_allocate: Decimal


def compute_totals(
    allocations: list[_HasAllocationFields], flows: list[_HasAcquiredField]
) -> Totals:
    """Legacy computeTotals_() — every aggregate the business rules depend on."""
    total_prev = sum((a.previous_requirement for a in allocations), Decimal("0"))
    total_today = sum((a.today_required for a in allocations), Decimal("0"))
    total_alloted = sum((a.alloted for a in allocations), Decimal("0"))
    total_balance = sum((a.balance for a in allocations), Decimal("0"))
    total_acquired = sum((f.today_acquired for f in flows), Decimal("0"))

    return Totals(
        total_previous_requirement=round3(total_prev),
        total_today_required=round3(total_today),
        total_alloted=round3(total_alloted),
        total_balance=round3(total_balance),
        total_acquired=round3(total_acquired),
        remaining_to_allocate=round3(max(Decimal("0"), total_acquired - total_alloted)),
    )


def assert_save_rules(totals: Totals, rules: BusinessRules) -> None:
    """
    Legacy assertSaveRules_(). Only require_positive_acquired is actually
    reachable in the current business-rule configuration — the other three
    checks are kept, exactly as in the legacy code, for the day they might be
    switched back on, but CLAUDE.md is explicit: do not flip them without an
    instruction.
    """
    if rules.require_positive_acquired and not (totals.total_acquired > 0):
        raise ValidationError(
            "Enter Today's Acquired metal in the Metal Flow panel before saving.",
            code="NO_ACQUIRED_METAL",
        )
    if rules.require_positive_alloted and not (totals.total_alloted > 0):
        raise ValidationError(
            "Enter the sector-wise Alloted quantities before saving.", code="NO_ALLOCATION"
        )
    if rules.block_over_allocation and (totals.total_alloted - totals.total_acquired) > get_settings().weight_epsilon:
        over = fmt3(totals.total_alloted - totals.total_acquired)
        raise ValidationError(
            f"Allocation exceeds Total Today’s Acquired by {over} kg. Reduce the allocation before saving.",
            code="OVER_ALLOCATED",
        )
    if rules.require_full_allocation and not nearly_equal(totals.total_alloted, totals.total_acquired):
        raise ValidationError(
            f"Complete the allocation before saving. {fmt3(totals.remaining_to_allocate)} kg is still remaining.",
            code="INCOMPLETE_ALLOCATION",
        )


def assert_revision_reason(reason: str | None, rules: BusinessRules) -> str:
    """Legacy assertRevisionReason_()."""
    text_value = (reason or "").strip()
    if rules.require_revision_reason:
        if not text_value:
            raise ValidationError("A revision reason is mandatory.", code="REVISION_REASON_REQUIRED")
        if len(text_value) < rules.min_revision_reason_length:
            raise ValidationError(
                f"The revision reason must be at least {rules.min_revision_reason_length} characters.",
                code="REVISION_REASON_TOO_SHORT",
            )
    return text_value[:1000]
