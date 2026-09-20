"""
services/scope_service.py
Royal Metal Allocation System — Python port

Ports the identity/authorization portion of AuditService.gs's isAdministrator_()
— deliberately relocated out of the audit service, since admin-check logic being
load-bearing for authorization has nothing to do with auditing (see
sessions/2026-09-19_rmas-legacy-review/session.md, per-file summary §1) — plus
the scope resolution from StagingService.gs's getUserScope_() / scopeAllows_() /
scopeAllowsFlow_().

Scope is resolved server-side on every request and is never accepted from the
client (CLAUDE.md section 6, rule 8).
"""

from dataclasses import dataclass

from models.user import AppUser


@dataclass(frozen=True)
class UserScope:
    """What a user may see. Mirrors legacy's getUserScope_() return shape.

    `flow_sector_ids` of None means "no explicit grants — fall back to party",
    exactly like legacy's flowSectorKeys: null. An empty list would mean
    something different and is deliberately not produced here.
    """

    user_id: int
    email: str
    is_admin: bool
    unrestricted: bool
    party_ids: frozenset[int]
    flow_sector_ids: frozenset[int] | None


def is_administrator(user: AppUser) -> bool:
    """Deny list always overrides an admin grant (CLAUDE.md section 6, rule 9).

    Note this only suppresses ADMIN STATUS, never login — matching legacy, where
    NON_ADMIN_EMAILS was consulted by isAdministrator_() alone.
    """
    if user.admin_denied:
        return False
    return bool(user.is_admin)


def build_scope(
    user: AppUser,
    party_ids: list[int],
    flow_sector_ids: list[int],
    all_party_ids: list[int],
) -> UserScope:
    """Assemble a user's effective scope.

    An administrator is unrestricted and sees every party. An operator sees only
    the parties granted to them.
    """
    admin = is_administrator(user)
    if admin:
        return UserScope(
            user_id=user.user_id,
            email=user.email,
            is_admin=True,
            unrestricted=True,
            party_ids=frozenset(all_party_ids),
            flow_sector_ids=None,
        )

    return UserScope(
        user_id=user.user_id,
        email=user.email,
        is_admin=False,
        unrestricted=False,
        party_ids=frozenset(party_ids),
        # No explicit grants -> None, meaning "fall back to party".
        flow_sector_ids=frozenset(flow_sector_ids) if flow_sector_ids else None,
    )


def scope_allows_party(scope: UserScope, party_id: int | None) -> bool:
    """Ports scopeAllows_()."""
    if scope.unrestricted:
        return True
    if party_id is None:
        return False
    return party_id in scope.party_ids


def scope_allows_flow(scope: UserScope, flow_sector_id: int, party_id: int | None) -> bool:
    """Ports scopeAllowsFlow_(): an explicit grant list wins; otherwise the
    sector's party decides."""
    if scope.unrestricted:
        return True
    if scope.flow_sector_ids is not None:
        return flow_sector_id in scope.flow_sector_ids
    return scope_allows_party(scope, party_id)
