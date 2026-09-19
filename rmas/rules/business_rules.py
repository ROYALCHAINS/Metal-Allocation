"""
business_rules.py
Royal Metal Allocation System — Python port

SINGLE SOURCE OF BUSINESS RULE TOGGLES. Ports Config.gs's RULES block.
Do not duplicate or override these values anywhere else in the codebase.

Where the legacy source and CLAUDE.md disagree on intent, the legacy source's
ACTUAL CODE PATHS win (per CLAUDE.md, "the legacy source wins"). Two toggle
groups below are marked accordingly:

  * ENFORCED   — read by a real conditional in the legacy .gs code, and by
                 the corresponding Python service here.
  * NOT ENFORCED (inert) — declared in Config.gs's RULES object and named in
                 CLAUDE.md's "currently enabled" list, but never read by any
                 legacy function. The behaviour they describe is real (e.g.
                 nothing forbids a zero previous requirement), but it exists
                 because no code forbids it, not because a check permits it.
                 Per an explicit decision on this port, these are kept as
                 DATA ONLY — do not add new guard-clause code around them.
                 Doing so would be a behaviour change relative to legacy 5H.

Do not flip DISABLED_BY_BUSINESS_DECISION to True without an explicit
instruction — see CLAUDE.md section 6. There is an unresolved, never-settled
conflict between the current code state (all four False) and an earlier
"final business decisions" document that wanted two of them True. That
conflict is not resolved by this port.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BusinessRules:
    # ---- ENFORCED ---------------------------------------------------
    # Carry-forward fallback: when nothing was saved on the rule date
    # (Monday -> Saturday, else yesterday), fall back to the most recent
    # saved date instead of resetting to 0.000. Skipped days must never
    # silently zero a balance.
    carry_forward_from_latest_saved: bool = True

    # There must be metal acquired on the date before an admin may save it.
    require_positive_acquired: bool = True

    allow_admin_revision: bool = True
    require_revision_reason: bool = True
    min_revision_reason_length: int = 10

    # Operator submission cross-check. Requirement is demand, Acquired is
    # supply; demand may legitimately exceed supply. Keep False.
    operator_required_within_acquired: bool = False

    # ---- DISABLED BY BUSINESS DECISION — DO NOT RE-ENABLE ------------
    # See CLAUDE.md section 6: this conflicts with an earlier, never-settled
    # "final business decisions" document. Raise the conflict, don't resolve it.
    require_full_allocation: bool = False       # Alloted need not equal Acquired
    require_positive_alloted: bool = False      # Zero allotment is permitted
    block_over_allocation: bool = False         # Alloted may exceed Acquired

    # ---- DECLARED BUT NOT ENFORCED (inert, data-only) ----------------
    # No legacy code path reads these three. Ported as documentation-only
    # constants per an explicit decision; do not wire up new enforcement.
    allow_zero_previous_requirement: bool = True
    allow_zero_closing_balance: bool = True
    saved_date_immutable_for_users: bool = True


@dataclass(frozen=True)
class SectorExpectations:
    """
    Legacy CONFIG.EXPECTED. STRICT was false in 5H, so a mismatch only
    warned and the sheet's actual contents were used. The true count was an
    open question (comment said 19, this constant said 21); per an explicit
    decision on this port, 21 is used as the working assumption for
    ALLOCATION_ROWS. Revisit if real source data disagrees.
    """

    allocation_rows: int = 21
    flow_rows: int = 8
    strict: bool = False


BUSINESS_RULES = BusinessRules()
SECTOR_EXPECTATIONS = SectorExpectations()

# Legacy DECIMALS / EPSILON / MAX_WEIGHT_KG live in config.py (Settings),
# not here, because they are numeric-precision constants rather than
# business-policy toggles that a business owner would flip.
WEIGHT_DECIMALS = 3
WEIGHT_EPSILON = Decimal("0.0005")
MAX_WEIGHT_KG = Decimal("100000")
