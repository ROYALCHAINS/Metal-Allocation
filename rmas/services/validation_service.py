"""
services/validation_service.py
Royal Metal Allocation System — Python port of ValidationService.gs

PARTIAL PORT. Only the key-normalisation helpers are here so far; the rest of
ValidationService.gs (computeTotals_, assertSaveRules_, assertRevisionReason_,
the weight assertions) is still to be ported. The numeric helpers that were
already needed live in services/weight_service.py.

NORMALISATION — DISCREPANCY WITH DATABASE_OVERVIEW.md, deliberately resolved in
favour of the legacy source (CLAUDE.md: "where this document and the legacy .gs
source disagree, the legacy source wins").

DATABASE_OVERVIEW.md says sector_key/party_key are "lowercase, with spaces,
dashes and punctuation removed", describing that as mirroring legacy. It does
not. ValidationService.gs:70-76 is:

    String(name)
      .replace(/[\\u2010-\\u2015\\u2212]/g, '-')   // en/em dash and minus -> hyphen
      .replace(/\\s+/g, ' ')                      // collapse whitespace runs
      .trim()
      .toLowerCase();

That is case-insensitive and whitespace-COLLAPSING, not whitespace-REMOVING,
and it keeps punctuation. So 'Royal Chain' normalises to 'royal chain', not
'royalchain'. Following the overview instead would make 'Royal Chain' and
'RoyalChain' collide as one key, which legacy treats as two different sectors,
and would not match keys derived from historical data.
"""

import re
from dataclasses import dataclass
from decimal import InvalidOperation

from rules.business_rules import MAX_WEIGHT_KG, business_rules
from services.exceptions import ValidationError
from services.weight_service import kg_to_grams

# en dash, em dash, horizontal bar, minus sign, etc. -> plain hyphen
_UNICODE_DASHES = re.compile("[‐-―−]")
_WHITESPACE_RUN = re.compile(r"\s+")

_MAX_WEIGHT_G = kg_to_grams(MAX_WEIGHT_KG)


def nearly_equal_g(left_g: int, right_g: int) -> bool:
    """Legacy's nearlyEqual_(), translated to exact integer grams.

    Legacy asks `abs(round3(a) - round3(b)) < 0.0005`. Both operands are already
    rounded to 3 decimals, so their difference is a multiple of 0.001 kg — and
    the smallest non-zero multiple, 0.001, is NOT less than 0.0005. The
    comparison therefore only ever succeeds when the two are the same value.

    In grams that is plain equality. The 0.0005 epsilon exists in legacy purely
    to absorb binary-float representation error; integer grams have none, so
    comparing exactly is both simpler and strictly more correct. Note this is
    why EPSILON must NOT be naively converted to "1 gram" — that would wrongly
    treat a real 1-gram difference as equal.
    """
    return left_g == right_g


def normalize_key(name: str | None) -> str:
    """Port of ValidationService.gs's normalizeSectorKey_().

    normalizePartyKey_() delegated to the same function in legacy
    (DataService.gs:51-53), so party keys and sector keys normalise identically.
    """
    text = "" if name is None else str(name)
    text = _UNICODE_DASHES.sub("-", text)
    text = _WHITESPACE_RUN.sub(" ", text)
    return text.strip().lower()


def _to_grams(value, label: str) -> int:
    """Parse an inbound weight in kilograms into integer grams.

    Mirrors legacy's coercion: null/empty is 0, and commas are stripped (the
    sheet and the browser both produce '1,234.500'). A float is refused outright
    — see services/weight_service.py.
    """
    if value is None or value == "":
        return 0
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        if not value:
            return 0
    try:
        return kg_to_grams(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("INVALID_NUMBER", f"{label} must be a valid number.") from exc
    except TypeError as exc:
        raise ValidationError(
            "INVALID_NUMBER", f"{label} must be a valid number (floats are not accepted)."
        ) from exc


def assert_signed_weight(value, label: str) -> int:
    """A DERIVED weight that may legitimately be negative — returns grams.

    Previous Requirement and Balance carry forward from the prior day's Balance,
    and since an allocation may exceed the requirement that balance can be
    negative, carrying the negative into the next day. Only the magnitude is
    sanity-checked. Ports assertSignedWeight_().
    """
    grams = _to_grams(value, label)
    if abs(grams) > _MAX_WEIGHT_G:
        raise ValidationError("VALUE_TOO_LARGE", f"{label} exceeds the maximum permitted weight.")
    return grams


def assert_valid_weight(value, label: str) -> int:
    """A weight INPUT, which may not be negative — returns grams.

    Ports assertValidWeight_().
    """
    grams = _to_grams(value, label)
    if grams < 0:
        raise ValidationError("NEGATIVE_VALUE", f"{label} cannot be negative.")
    if grams > _MAX_WEIGHT_G:
        raise ValidationError("VALUE_TOO_LARGE", f"{label} exceeds the maximum permitted weight.")
    return grams


def compute_balance_g(previous_requirement_g: int, today_required_g: int, alloted_g: int) -> int:
    """balance = previous_requirement + today_required - alloted.

    The one equation the whole system exists to evaluate (CLAUDE.md section 1).
    Exact in integer grams — legacy had to round the result because it worked in
    binary floats.
    """
    return previous_requirement_g + today_required_g - alloted_g


@dataclass(frozen=True)
class Totals:
    """Every aggregate the business rules depend on, in grams.

    Ports computeTotals_(). Legacy rounded each total after summing because
    float addition drifts; integer sums are exact, so no rounding is needed and
    the results are identical for any valid 3-decimal input.
    """

    total_previous_requirement_g: int
    total_today_required_g: int
    total_alloted_g: int
    total_balance_g: int
    total_acquired_g: int
    remaining_to_allocate_g: int


def compute_totals(allocation_rows, flow_rows) -> Totals:
    """`allocation_rows` need .previous_requirement_g/.today_required_g/
    .alloted_g/.balance_g; `flow_rows` need .today_acquired_g."""
    total_previous = sum(r.previous_requirement_g for r in allocation_rows)
    total_required = sum(r.today_required_g for r in allocation_rows)
    total_alloted = sum(r.alloted_g for r in allocation_rows)
    total_balance = sum(r.balance_g for r in allocation_rows)
    total_acquired = sum(r.today_acquired_g for r in flow_rows)

    return Totals(
        total_previous_requirement_g=total_previous,
        total_today_required_g=total_required,
        total_alloted_g=total_alloted,
        total_balance_g=total_balance,
        total_acquired_g=total_acquired,
        # Legacy clamps at zero: over-allocating leaves nothing "remaining".
        remaining_to_allocate_g=max(0, total_acquired - total_alloted),
    )


def assert_save_rules(totals: Totals) -> None:
    """The four togglable save rules. Ports assertSaveRules_().

    Only REQUIRE_POSITIVE_ACQUIRED is enabled. The other three are disabled by
    business decision and must not be re-enabled without instruction — there is
    an unresolved conflict with an earlier "final business decisions" document
    (CLAUDE.md section 6).
    """
    if business_rules.require_positive_acquired and totals.total_acquired_g <= 0:
        raise ValidationError(
            "NO_ACQUIRED_METAL",
            "Enter Today's Acquired metal in the Metal Flow panel before saving.",
        )

    if business_rules.require_positive_alloted and totals.total_alloted_g <= 0:
        raise ValidationError(
            "NO_ALLOCATION", "Enter the sector-wise Alloted quantities before saving."
        )

    # Legacy: (totalAlloted - totalAcquired) > EPSILON. In exact grams any
    # positive difference is a real over-allocation.
    if business_rules.block_over_allocation and totals.total_alloted_g > totals.total_acquired_g:
        raise ValidationError(
            "OVER_ALLOCATED",
            "Allocation exceeds Total Today's Acquired. Reduce the allocation before saving.",
        )

    if business_rules.require_full_allocation and not nearly_equal_g(
        totals.total_alloted_g, totals.total_acquired_g
    ):
        raise ValidationError(
            "INCOMPLETE_ALLOCATION",
            "Complete the allocation before saving; some acquired metal is still unallocated.",
        )


@dataclass
class NormalizedAllocationRow:
    sector_id: int
    sector_name: str
    priority: str
    purity: str
    party_id: int
    previous_requirement_g: int
    today_required_g: int
    alloted_g: int
    balance_g: int


@dataclass
class NormalizedFlowRow:
    flow_sector_id: int
    sector_name: str
    party_id: int
    today_acquired_g: int


@dataclass
class NormalizedPayload:
    allocations: list[NormalizedAllocationRow]
    metal_flow: list[NormalizedFlowRow]
    totals: Totals


def validate_and_normalize_payload(
    submitted_allocations,
    submitted_flow,
    allocation_defs,
    flow_defs,
) -> NormalizedPayload:
    """Rebuild the payload from the live sector definitions. Ports
    validateAndNormalizePayload_().

    SECURITY: every identifying field — sector name, party, purity, priority —
    is taken from the DATABASE definitions, never from the client. The client
    supplies only the three weights. Submitted rows are matched by sector id, so
    **row order can never corrupt a save**, and a row for a sector outside the
    caller's definitions simply has nowhere to land.

    `allocation_defs`/`flow_defs` are (sector, party) pairs from
    repository/sector_repo.py, already narrowed to the caller's scope — so an
    operator can only ever save rows for sectors they may see.
    """
    if not allocation_defs or not flow_defs:
        raise ValidationError(
            "INCOMPLETE_PAYLOAD",
            "No sectors are mapped to your party. Ask an administrator to check the "
            "Party column.",
        )

    submitted_alloc_by_id = {row.sector_id: row for row in submitted_allocations}
    submitted_flow_by_id = {row.flow_sector_id: row for row in submitted_flow}

    if len(submitted_alloc_by_id) != len(allocation_defs):
        raise ValidationError(
            "ALLOCATION_ROW_COUNT",
            f"Expected {len(allocation_defs)} allocation rows but received "
            f"{len(submitted_alloc_by_id)}.",
        )
    if len(submitted_flow_by_id) != len(flow_defs):
        raise ValidationError(
            "FLOW_ROW_COUNT",
            f"Expected {len(flow_defs)} Metal Flow rows but received "
            f"{len(submitted_flow_by_id)}.",
        )

    allocations = []
    for sector, _party in allocation_defs:
        submitted = submitted_alloc_by_id.get(sector.sector_id)
        if submitted is None:
            raise ValidationError(
                "SECTOR_MISSING",
                f'Allocation data for "{sector.sector_name}" was not received.',
            )

        label = sector.sector_name
        # Carried forward from the prior balance, so it may be negative.
        previous_requirement_g = assert_signed_weight(
            submitted.previous_requirement_kg, f"Previous Requirement ({label})"
        )
        today_required_g = assert_valid_weight(
            submitted.today_required_kg, f"Today's Required Weight ({label})"
        )
        alloted_g = assert_valid_weight(submitted.alloted_kg, f"Alloted ({label})")

        allocations.append(
            NormalizedAllocationRow(
                sector_id=sector.sector_id,
                sector_name=sector.sector_name,
                priority=sector.priority,
                purity=sector.purity,
                party_id=sector.party_id,
                previous_requirement_g=previous_requirement_g,
                today_required_g=today_required_g,
                alloted_g=alloted_g,
                balance_g=compute_balance_g(
                    previous_requirement_g, today_required_g, alloted_g
                ),
            )
        )

    metal_flow = []
    for flow_sector, _party in flow_defs:
        submitted = submitted_flow_by_id.get(flow_sector.flow_sector_id)
        if submitted is None:
            raise ValidationError(
                "FLOW_SECTOR_MISSING",
                f'Metal Flow data for "{flow_sector.sector_name}" was not received.',
            )
        metal_flow.append(
            NormalizedFlowRow(
                flow_sector_id=flow_sector.flow_sector_id,
                sector_name=flow_sector.sector_name,
                party_id=flow_sector.party_id,
                today_acquired_g=assert_valid_weight(
                    submitted.today_acquired_kg, f"Today's Acquired ({flow_sector.sector_name})"
                ),
            )
        )

    return NormalizedPayload(
        allocations=allocations,
        metal_flow=metal_flow,
        totals=compute_totals(allocations, metal_flow),
    )


def assert_revision_reason(reason: str | None) -> str:
    """Ports assertRevisionReason_() — mandatory, min length, truncated at 1000."""
    text = "" if reason is None else str(reason).strip()
    if business_rules.require_revision_reason:
        if not text:
            raise ValidationError("REVISION_REASON_REQUIRED", "A revision reason is mandatory.")
        if len(text) < business_rules.min_revision_reason_length:
            raise ValidationError(
                "REVISION_REASON_TOO_SHORT",
                "The revision reason must be at least "
                f"{business_rules.min_revision_reason_length} characters.",
            )
    return text[:1000]
