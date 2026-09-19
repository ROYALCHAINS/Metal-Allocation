"""
date_service.py
Royal Metal Allocation System — Python port

Ports DateService.gs. All dates are `datetime.date` (CLAUDE.md 6.6 — never a
timezone-naive datetime); the legacy 'yyyy-MM-dd' string-key gymnastics exist
only where a display string is genuinely needed. The application timezone is
fixed at Asia/Kolkata (CLAUDE.md 6.7).

THE BUSINESS RULE (do not "simplify" this — CLAUDE.md 6.4):
    Monday        -> selected date - 2 days (Saturday)
    Any other day -> selected date - 1 day
This encodes the six-day working week.
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from rmas.config import get_settings

_MONTH_ABBR = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]
_WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Python's date.weekday(): Monday == 0.
_MONDAY = 0


def app_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


def today() -> date:
    """Legacy todayKey_() — today's date in the application timezone."""
    from datetime import datetime

    return datetime.now(app_timezone()).date()


def previous_source_date(selected_date: date) -> date:
    """
    Legacy previousSourceDateKey_(). Monday looks back to Saturday (-2 days);
    every other day looks back 1 day.
    """
    if selected_date.weekday() == _MONDAY:
        return selected_date - timedelta(days=2)
    return selected_date - timedelta(days=1)


def format_display_date(d: date | None) -> str:
    """Legacy formatDisplayDate_() — e.g. 'Mon, 17-Aug-2026'. '' for None."""
    if d is None:
        return ""
    weekday = _WEEKDAY_ABBR[d.weekday()]
    month = _MONTH_ABBR[d.month - 1]
    return f"{weekday}, {d.day:02d}-{month}-{d.year:04d}"


def short_date_label(d: date | None) -> str:
    """Legacy shortDateLabel_() — e.g. '01 Sep', used on chart axes."""
    if d is None:
        return ""
    return f"{d.day:02d} {_MONTH_ABBR[d.month - 1]}"
