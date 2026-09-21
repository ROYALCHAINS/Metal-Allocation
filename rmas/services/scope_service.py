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


# --------------------------------------------------------- access diagnostics

_FLOW_SCOPE_UNRESTRICTED = "Unrestricted — an administrator sees every party's flow rows."
# Verbatim from legacy's debugScreenFlags (StagingService.gs:854), down to the
# plain hyphen. Zero rows in user_flow_scope means "derive access from the
# party", NOT "no access" — see models/user.py. Every live account is in this
# state, so this is the string people will actually read.
_FLOW_SCOPE_FALLBACK = "(none configured - falling back to the Party column)"


@dataclass(frozen=True)
class AccessDiagnosis:
    """Why the server treats ONE caller the way it does — never anybody else."""

    email: str
    display_name: str
    is_administrator: bool
    admin_denied: bool
    is_active: bool
    party_names: tuple[str, ...]
    flow_scope: str
    diagnosis: tuple[str, ...]


def diagnose_access(
    user: AppUser,
    scope: UserScope,
    party_names: list[str],
    flow_sector_names: list[str],
) -> AccessDiagnosis:
    """Ports the surviving half of diagnoseAdminAccess() (AuditReportService.gs:42).

    Legacy returned CONFIG.ADMIN_EMAILS and CONFIG.NON_ADMIN_EMAILS wholesale.
    Rule 10 forbids both, so neither the administrator roster nor the deny list
    appears here — only this caller's own flags. Legacy could afford the roster
    because the function was reachable only from the Apps Script editor; an HTTP
    route has no such containment.

    Also dropped as unportable: the Apps Script redeploy advice, the
    '@yourcompany.com' placeholder branch (dead even in legacy), and the
    "identity could not be resolved" branch — get_current_user raises 401 long
    before this runs. Do not restore them.
    """
    admin = is_administrator(user)
    notes: list[str] = []

    if user.admin_denied:
        notes.append(
            "This account is on the administrator deny list, so administrator "
            "rights are refused regardless of any administrator grant on the "
            "account. Ask an administrator to clear the deny flag."
        )
    elif not admin:
        notes.append(
            "This account is not flagged as an administrator, so "
            "administrator-only screens such as the Audit Log are hidden."
        )

    if admin:
        notes.append("Administrator access is active for this account.")

    if not user.is_active:
        notes.append(
            "This account is marked inactive. It cannot sign in again until an "
            "administrator reactivates it."
        )

    if not scope.unrestricted and not scope.party_ids:
        notes.append(
            "No party is assigned to this account, so the allocation, report "
            "and dashboard screens will be empty."
        )

    # ORDER MATTERS: build_scope() leaves flow_sector_ids None for ADMINISTRATORS
    # too, so testing the fallback first would tell every admin they have no flow
    # grants. Unrestricted has to win.
    if scope.unrestricted:
        flow_scope = _FLOW_SCOPE_UNRESTRICTED
    elif scope.flow_sector_ids is None:
        flow_scope = _FLOW_SCOPE_FALLBACK
        notes.append(
            "No explicit Metal Flow grants are configured, so flow access is "
            "derived from your party. This is the normal configuration, not a "
            "missing permission."
        )
    else:
        flow_scope = ", ".join(flow_sector_names)

    return AccessDiagnosis(
        email=user.email,
        display_name=user.display_name or user.email,
        is_administrator=admin,
        admin_denied=bool(user.admin_denied),
        is_active=bool(user.is_active),
        party_names=tuple(party_names),
        flow_scope=flow_scope,
        diagnosis=tuple(notes),
    )
