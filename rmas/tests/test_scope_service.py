"""tests/test_scope_service.py — admin resolution and operator scope.

Deny list always overrides an admin grant (CLAUDE.md section 6, rule 9), and an
empty flow-grant list means "fall back to party", never "no access"
(StagingService.gs's scopeAllowsFlow_). Pure functions, no DB needed.
"""

from models.user import AppUser
from services.scope_service import (
    build_scope,
    diagnose_access,
    is_administrator,
    scope_allows_flow,
    scope_allows_party,
)


def _user(
    *, is_admin: bool, admin_denied: bool = False, is_active: bool = True
) -> AppUser:
    return AppUser(
        user_id=1,
        email="x@example.com",
        display_name="X",
        is_admin=is_admin,
        admin_denied=admin_denied,
        is_active=is_active,
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


# --------------------------------------------------------- access diagnostics
#
# Ports the surviving half of diagnoseAdminAccess(). The roster fields legacy
# returned are gone (rule 10); what remains must describe the caller and nobody
# else, and must never call the flow-scope fallback a denial.

FALLBACK = "(none configured - falling back to the Party column)"


def _operator_scope(*, party_ids=frozenset({1}), flow_sector_ids=None):
    return build_scope(
        _user(is_admin=False),
        party_ids=list(party_ids),
        flow_sector_ids=list(flow_sector_ids) if flow_sector_ids else [],
        all_party_ids=[1, 2],
    )


def _admin_scope():
    return build_scope(
        _user(is_admin=True), party_ids=[], flow_sector_ids=[], all_party_ids=[1, 2]
    )


def test_a_denied_admin_is_told_the_deny_list_is_why() -> None:
    user = _user(is_admin=True, admin_denied=True)
    result = diagnose_access(user, _operator_scope(), ["Royal Chain"], [])

    assert result.is_administrator is False
    assert result.admin_denied is True
    assert any("deny list" in line for line in result.diagnosis)
    assert not any("Administrator access is active" in line for line in result.diagnosis)


def test_an_operator_is_told_the_admin_flag_is_missing() -> None:
    result = diagnose_access(_user(is_admin=False), _operator_scope(), ["Royal Chain"], [])

    assert any("not flagged as an administrator" in line for line in result.diagnosis)
    assert not any("deny list" in line for line in result.diagnosis)


def test_an_administrator_is_told_access_is_active() -> None:
    result = diagnose_access(_user(is_admin=True), _admin_scope(), ["Royal Chain"], [])

    assert result.is_administrator is True
    assert any("Administrator access is active" in line for line in result.diagnosis)


def test_an_inactive_account_is_called_out() -> None:
    user = _user(is_admin=False, is_active=False)
    result = diagnose_access(user, _operator_scope(), ["Royal Chain"], [])

    assert result.is_active is False
    assert any("marked inactive" in line for line in result.diagnosis)


def test_an_operator_with_no_parties_is_told_the_screens_will_be_empty() -> None:
    scope = _operator_scope(party_ids=frozenset())
    result = diagnose_access(_user(is_admin=False), scope, [], [])

    assert any("No party is assigned" in line for line in result.diagnosis)


def test_empty_flow_grants_render_as_party_fallback_never_as_a_deny() -> None:
    """Zero rows in user_flow_scope means "derive from party", NOT "no access".

    Every live account is in this state, so this is the string people read.
    """
    result = diagnose_access(_user(is_admin=False), _operator_scope(), ["Royal Chain"], [])

    assert result.flow_scope == FALLBACK
    assert any("normal configuration, not a missing permission" in line
               for line in result.diagnosis)


def test_an_administrator_is_not_described_as_falling_back_to_party() -> None:
    """build_scope leaves flow_sector_ids None for admins too — order matters.

    Testing the fallback branch before `unrestricted` would tell every
    administrator they have no flow grants.
    """
    scope = _admin_scope()
    assert scope.flow_sector_ids is None, "precondition: admins carry no explicit grants"

    result = diagnose_access(_user(is_admin=True), scope, ["Royal Chain"], [])
    assert result.flow_scope != FALLBACK
    assert "Unrestricted" in result.flow_scope


def test_explicit_flow_grants_are_listed() -> None:
    scope = _operator_scope(flow_sector_ids=frozenset({30}))
    result = diagnose_access(_user(is_admin=False), scope, ["Royal Chain"], ["Royal Chain"])

    assert result.flow_scope == "Royal Chain"


def test_no_diagnosis_line_names_an_account() -> None:
    """Legacy quoted the caller's email and the whole ADMIN_EMAILS list. Rule 10."""
    for user in (_user(is_admin=True), _user(is_admin=False),
                 _user(is_admin=True, admin_denied=True)):
        result = diagnose_access(user, _operator_scope(), ["Royal Chain"], [])
        assert not any("@" in line for line in result.diagnosis)
