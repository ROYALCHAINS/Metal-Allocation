"""tests/test_validation_service.py — key normalisation, ported from ValidationService.gs.

These tests pin the LEGACY behaviour, which differs from DATABASE_OVERVIEW.md's
description of it. The overview says keys have "spaces, dashes and punctuation
removed"; ValidationService.gs:70-76 collapses whitespace and lowercases but
keeps spaces and punctuation. CLAUDE.md says the legacy source wins, so that is
what is pinned here — see services/validation_service.py's docstring.
"""

import pytest

from services.validation_service import normalize_key


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Royal Chain", "royal chain"),
        ("Aditya Birla", "aditya birla"),
        ("ARK", "ark"),
        ("IHG", "ihg"),
        # Trailing/leading whitespace is trimmed (legacy .trim()).
        ("  Aalishaan  ", "aalishaan"),
        # Whitespace runs collapse to a single space, they are NOT removed.
        ("Royal    Chain", "royal chain"),
        ("Royal\tChain", "royal chain"),
        ("", ""),
    ],
)
def test_normalize_key(raw: str, expected: str) -> None:
    assert normalize_key(raw) == expected


def test_none_normalises_to_empty_string() -> None:
    assert normalize_key(None) == ""


def test_spaces_are_kept_not_stripped() -> None:
    """The documented difference from DATABASE_OVERVIEW.md.

    If spaces were removed as the overview claims, these two would collide into
    one key — legacy treats them as two distinct sectors.
    """
    assert normalize_key("Royal Chain") == "royal chain"
    assert normalize_key("RoyalChain") == "royalchain"
    assert normalize_key("Royal Chain") != normalize_key("RoyalChain")


@pytest.mark.parametrize(
    "dash_char",
    ["‐", "‑", "‒", "–", "—", "―", "−"],
)
def test_unicode_dashes_become_plain_hyphens(dash_char: str) -> None:
    """A sheet pasted from Word/Excel can carry en/em dashes — legacy folds them
    so 'X–Y' and 'X-Y' match."""
    assert normalize_key(f"Alpha{dash_char}Beta") == "alpha-beta"


def test_case_insensitivity() -> None:
    assert normalize_key("MALABAR") == normalize_key("malabar") == "malabar"
