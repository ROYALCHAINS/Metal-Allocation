"""
services/date_service.py
Royal Metal Allocation System — Python port

Ports DateService.gs. The one rule that matters: for a selected date, the
carry-forward "rule date" is Saturday if the selected date is a Monday,
otherwise yesterday — encoding a six-day working week (CLAUDE.md section 6,
rule 4). Do not simplify this to "always yesterday".

Legacy stored dates at 12:00 local specifically to survive DST/UTC rollover
(CLAUDE.md section 6, rule 6). A proper PostgreSQL DATE column supersedes
that hack — there is no `dateKeyToStorageDate_`/STORAGE_HOUR equivalent
here, deliberately.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from rules.business_rules import business_rules

APP_TIMEZONE = "Asia/Kolkata"

# Mirrors DateService.gs's toDateKey_() accepted string formats.
_DATE_STRING_FORMATS = (
    "%Y-%m-%d",  # yyyy-MM-dd
    "%d/%m/%Y",  # dd/MM/yyyy
    "%d-%m-%Y",  # dd-MM-yyyy
    "%d-%b-%Y",  # dd-MMM-yyyy, e.g. 17-Aug-2026
)


def to_date_key(value: date | datetime | str) -> date:
    """Normalise any accepted legacy date representation to a `date`."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = value.strip()
    for fmt in _DATE_STRING_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {value!r}")


def previous_source_date(selected: date) -> date:
    """The carry-forward rule date: Monday looks back to Saturday (-2 days),
    every other day looks back 1 day.
    """
    if selected.weekday() == 0:  # Monday
        return selected - timedelta(days=2)
    return selected - timedelta(days=1)


def today_key(tz_name: str = APP_TIMEZONE) -> date:
    """Today's date in the application timezone."""
    return datetime.now(ZoneInfo(tz_name)).date()


def format_display_date(value: date) -> str:
    """Mirrors DateService.gs's formatDisplayDate_(), e.g. 'Mon, 17-Aug-2026'."""
    return value.strftime("%a, %d-%b-%Y")


@dataclass(frozen=True)
class SourceDate:
    """Where a date's carried-forward figures come from."""

    rule_date: date
    # ISO string, or None when there is no source date at all.
    source_date: str | None
    used_fallback: bool


def resolve_source_date(
    selected: date,
    *,
    date_exists: Callable[[str], bool],
    latest_date_before: Callable[[str], str | None],
) -> SourceDate:
    """THE source-date rule. One implementation, two callers.

    The screen model and the forward cascade must agree exactly, or the Daily
    Allocation screen will show different figures from the ledger it was
    computed against. Rather than two copies kept in step by discipline, this
    is one function called twice — with repository-backed lookups from the
    screen model, and set-backed ones from the (pure) cascade service. That is
    also why the lookups are injected: this module stays free of any database
    dependency, and cascade_service can stay a pure function.

    TWO SUBTLETIES, both load-bearing:

    The fallback searches for the latest saved date before SELECTED, not
    before RULE_DATE. It can therefore return a date LATER than the rule date:
    selected Monday, rule date Saturday, Saturday never saved but Sunday was —
    the source is Sunday. That is legacy's behaviour and it is preserved.

    Callers resolve PER LEDGER. Allocation and Metal Flow can legitimately fall
    back to different dates, which is why allocation_repo and flow_repo mirror
    each other instead of sharing a query.
    """
    rule_date = previous_source_date(selected)
    rule_iso = rule_date.isoformat()

    if date_exists(rule_iso):
        return SourceDate(rule_date=rule_date, source_date=rule_iso, used_fallback=False)

    if not business_rules.carry_forward_from_latest_saved:
        return SourceDate(rule_date=rule_date, source_date=None, used_fallback=False)

    # A skipped day must never silently reset a balance to zero (rule 5).
    fallback = latest_date_before(selected.isoformat())
    return SourceDate(
        rule_date=rule_date, source_date=fallback, used_fallback=fallback is not None
    )
