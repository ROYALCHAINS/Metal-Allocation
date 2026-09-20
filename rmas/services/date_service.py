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

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

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
