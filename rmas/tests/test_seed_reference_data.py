"""tests/test_seed_reference_data.py — reference data is loaded verbatim.

Sector, party, priority and purity values come from the Metal Generator sheet
and are stored exactly as written (CLAUDE.md section 6, rule 15 / rule 23).
Nothing is parsed, renumbered or invented; the only rule enforced here is that
NOT NULL columns cannot be blank.
"""

import pytest

from seed_reference_data import read_priority


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Priority 1", "Priority 1"),
        ("Priority 6", "Priority 6"),
        # Only trimmed — never re-cased, renumbered or reformatted.
        ("  Priority 3  ", "Priority 3"),
        ("priority 2", "priority 2"),
        ("P1", "P1"),
        ("1", "1"),
        ("Urgent", "Urgent"),
    ],
)
def test_priority_is_stored_verbatim(raw: str, expected: str) -> None:
    assert read_priority(raw, "Some Sector") == expected


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_blank_priority_is_refused(raw) -> None:
    """sector.priority is TEXT NOT NULL — refuse rather than invent a value."""
    with pytest.raises(ValueError, match="TEXT NOT NULL"):
        read_priority(raw, "Some Sector")


def test_error_names_the_offending_sector() -> None:
    """The message has to say which row to go and look at."""
    with pytest.raises(ValueError, match="RC Customer Orders"):
        read_priority("", "RC Customer Orders")


def test_the_label_is_not_reformatted_into_a_number() -> None:
    """The whole point of storing TEXT: legacy shows this string to users, in
    report filter dropdowns and as the dashboard's 'by priority' grouping key."""
    assert read_priority("Priority 1", "s") == "Priority 1"
    assert read_priority("Priority 1", "s") != "1"
