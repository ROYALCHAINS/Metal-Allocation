"""tests/test_scope_service.py — admin resolution and operator scope.

Deny list always overrides an admin grant (CLAUDE.md section 6, rule 9), and an
empty flow-grant list means "fall back to party", never "no access"
(StagingService.gs's scopeAllowsFlow_). Pure functions, no DB needed.
"""

from models.user import AppUser
from services.scope_service import (
    build_scope,
    is_administrator,
    scope_allows_flow,
    scope_allows_party,
)


def _user(*, is_admin: bool, admin_denied: bool = False) -> AppUser:
    return AppUser(
        user_id=1,
        email="x@example.com",
        display_name="X",
        is_admin=is_admin,
        admin_denied=admin_denied,
        is_active=True,
        password_hash="unused",
    )


def test_admin_is_administrator() -> None:
    assert is_administrator(_user(is_admin=True)) is True


def test_operator_is_not_administrator() -> None:
    assert is_administrator(_user(is_admin=False)) is False


def test_denied_admin_is_not_administrator() -> None:
    """The deny list always overrides an admin grant, with no exception."""
    assert is_administrator(_user(is_admin=True, admin_denied=True)) is False


def test_denied_operator_is_not_administrator() -> None:
    assert is_administrator(_user(is_admin=False, admin_denied=True)) is False


def test_admin_scope_is_unrestricted_and_sees_all_parties() -> None:
    scope = build_scope(_user(is_admin=True), party_ids=[], flow_sector_ids=[], all_party_ids=[1, 2, 3])
    assert scope.unrestricted is True
    assert scope.party_ids == frozenset({1, 2, 3})
    assert scope_allows_party(scope, 99) is True


def test_operator_scope_is_limited_to_granted_parties() -> None:
    scope = build_scope(
        _user(is_admin=False), party_ids=[2], flow_sector_ids=[], all_party_ids=[1, 2, 3]
    )
    assert scope.unrestricted is False
    assert scope_allows_party(scope, 2) is True
    assert scope_allows_party(scope, 1) is False
    assert scope_allows_party(scope, None) is False


def test_denied_admin_gets_operator_scope_not_admin_scope() -> None:
    """A denied admin must be scoped like an operator, not handed everything."""
    scope = build_scope(
        _user(is_admin=True, admin_denied=True),
        party_ids=[2],
        flow_sector_ids=[],
        all_party_ids=[1, 2, 3],
    )
    assert scope.unrestricted is False
    assert scope_allows_party(scope, 1) is False


def test_no_flow_grants_falls_back_to_party() -> None:
    """Zero rows in user_flow_scope means 'derive from party', NOT 'no access'."""
    scope = build_scope(
        _user(is_admin=False), party_ids=[2], flow_sector_ids=[], all_party_ids=[1, 2]
    )
    assert scope.flow_sector_ids is None
    # Flow sector 50 belongs to party 2, which the operator holds.
    assert scope_allows_flow(scope, flow_sector_id=50, party_id=2) is True
    # Flow sector 51 belongs to party 1, which they do not.
    assert scope_allows_flow(scope, flow_sector_id=51, party_id=1) is False


def test_explicit_flow_grants_win_over_party() -> None:
    scope = build_scope(
        _user(is_admin=False), party_ids=[2], flow_sector_ids=[50], all_party_ids=[1, 2]
    )
    assert scope.flow_sector_ids == frozenset({50})
    assert scope_allows_flow(scope, flow_sector_id=50, party_id=2) is True
    # Granted parties do NOT widen an explicit flow grant list.
    assert scope_allows_flow(scope, flow_sector_id=99, party_id=2) is False
