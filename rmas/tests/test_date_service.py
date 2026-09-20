"""tests/test_date_service.py — carry-forward rule and date parsing.

Proves the ported carry-forward rule matches DateService.gs's
previousSourceDateKey_() for every day of the week, not just the Monday
special case.
"""

from datetime import date

import pytest

from services.date_service import format_display_date, previous_source_date, to_date_key


@pytest.mark.parametrize(
    "selected, expected",
    [
        (date(2026, 8, 17), date(2026, 8, 15)),  # Monday -> Saturday (-2)
        (date(2026, 8, 18), date(2026, 8, 17)),  # Tuesday -> Monday (-1)
        (date(2026, 8, 19), date(2026, 8, 18)),  # Wednesday -> Tuesday
        (date(2026, 8, 20), date(2026, 8, 19)),  # Thursday -> Wednesday
        (date(2026, 8, 21), date(2026, 8, 20)),  # Friday -> Thursday
        (date(2026, 8, 22), date(2026, 8, 21)),  # Saturday -> Friday
        (date(2026, 8, 23), date(2026, 8, 22)),  # Sunday -> Saturday
    ],
)
def test_previous_source_date(selected: date, expected: date) -> None:
    assert previous_source_date(selected) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-08-17", date(2026, 8, 17)),
        ("17/08/2026", date(2026, 8, 17)),
        ("17-08-2026", date(2026, 8, 17)),
        ("17-Aug-2026", date(2026, 8, 17)),
    ],
)
def test_to_date_key_string_formats(text: str, expected: date) -> None:
    assert to_date_key(text) == expected


def test_to_date_key_passthrough() -> None:
    d = date(2026, 8, 17)
    assert to_date_key(d) == d


def test_to_date_key_rejects_unknown_format() -> None:
    with pytest.raises(ValueError):
        to_date_key("Aug 17 2026")


def test_format_display_date() -> None:
    assert format_display_date(date(2026, 8, 17)) == "Mon, 17-Aug-2026"
