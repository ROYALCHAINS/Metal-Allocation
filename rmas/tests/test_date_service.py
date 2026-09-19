"""
Golden-value tests for the carry-forward rule (DateService.gs's
previousSourceDateKey_) and display formatting. No DB required.
"""

from datetime import date

from rmas.services.date_service import format_display_date, previous_source_date, short_date_label


def test_monday_looks_back_two_days_to_saturday():
    monday = date(2026, 9, 21)
    assert monday.weekday() == 0  # sanity: this really is a Monday
    assert previous_source_date(monday) == date(2026, 9, 19)  # Saturday


def test_tuesday_looks_back_one_day():
    tuesday = date(2026, 9, 22)
    assert previous_source_date(tuesday) == date(2026, 9, 21)


def test_sunday_looks_back_one_day_to_saturday():
    sunday = date(2026, 9, 20)
    assert previous_source_date(sunday) == date(2026, 9, 19)


def test_month_boundary_monday():
    monday = date(2026, 10, 5)
    assert monday.weekday() == 0
    assert previous_source_date(monday) == date(2026, 10, 3)


def test_format_display_date_matches_legacy_pattern():
    assert format_display_date(date(2026, 8, 17)) == "Mon, 17-Aug-2026"


def test_format_display_date_none_is_empty_string():
    assert format_display_date(None) == ""


def test_short_date_label():
    assert short_date_label(date(2026, 9, 1)) == "01 Sep"
