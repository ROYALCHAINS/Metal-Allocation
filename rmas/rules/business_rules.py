"""
rules/business_rules.py
Royal Metal Allocation System — Python port

SINGLE SOURCE OF BUSINESS RULE TOGGLES. Ports Config.gs's RULES block plus
the adjoining numeric constants (CLAUDE.md section 2). Do not duplicate or
override these values anywhere else in the codebase.

Where the legacy source and CLAUDE.md disagree on intent, the legacy
source's actual code paths win (CLAUDE.md: "the legacy source wins").

Two of the four DISABLED toggles below conflict with an earlier, never-
settled "final business decisions" document that wanted them enabled. That
conflict is recorded, not resolved, here — do not flip them without an
explicit instruction (CLAUDE.md section 6).

Three toggles are declared in Config.gs's RULES block and named in
CLAUDE.md's "currently enabled" list, but are never read by any conditional
anywhere in the legacy source (confirmed by full-source review — see
sessions/2026-09-19_rmas-legacy-review/session.md). The behaviour they
describe is real — e.g. nothing forbids a zero previous requirement — but it
holds because no code forbids it, not because a check permits it. They are
kept here as DATA ONLY. Do not add new guard-clause code around them without
an explicit decision — doing so would be a behaviour change relative to
legacy build 5H, not a straight port. (Open question #2,
sessions/2026-09-19_rmas-legacy-review/session.md.)
"""

from dataclasses import dataclass
from decimal import Decimal

DECIMALS = 3
EPSILON = Decimal("0.0005")
MAX_WEIGHT_KG = Decimal("100000")
TIMEZONE_FALLBACK = "Asia/Kolkata"
LOCK_TIMEOUT_MS = 30_000
REQUEST_ID_TTL_SECONDS = 900


@dataclass(frozen=True)
class BusinessRules:
    # ---- Enforced by a real conditional in the legacy source --------------
    require_positive_acquired: bool = True
    allow_admin_revision: bool = True
    require_revision_reason: bool = True
    min_revision_reason_length: int = 10
    carry_forward_from_latest_saved: bool = True

    # ---- Disabled by business decision — do not re-enable ------------------
    # CLAUDE.md section 6: conflicts with an earlier, never-settled "final
    # business decisions" document. Raise the conflict, don't resolve it.
    require_full_allocation: bool = False              # Alloted need not equal Acquired
    require_positive_alloted: bool = False             # Zero allotment is permitted
    block_over_allocation: bool = False                # Alloted may exceed Acquired
    operator_required_within_acquired: bool = False    # Requirement not capped by supply

    # ---- Declared in Config.gs, never read by any legacy conditional -------
    # Inert / documentary only — see module docstring.
    allow_zero_previous_requirement: bool = True
    allow_zero_closing_balance: bool = True
    saved_date_immutable_for_users: bool = True


business_rules = BusinessRules()
