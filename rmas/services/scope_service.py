"""
scope_service.py
Royal Metal Allocation System — Python port

Ports StagingService.gs's scope-resolution half (getUserScope_,
scopeAllows_, scopeAllowsFlow_, filterRowsByScope_, filterFlowRowsByScope_,
buildSectorPartyMaps_, rowPartyKey_, scopedSectorNames_). The submission
workflow itself lives in services/staging_service.py.

CLAUDE.md 6.8: scope is enforced server-side on every request, without
exception. A party/sector filter from the client is never authoritative —
routers must intersect it with what this module resolves, never take it as-is.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from rmas.models.party import Party
from rmas.models.sector import AllocationSector, FlowSector
from rmas.models.user import User, UserRole
from rmas.repository import sector_repo
from rmas.services.dto import AllocationModel


@dataclass(frozen=True)
class UserScope:
    email: str
    display_name: str
    is_admin: bool
    role: str  # "ADMIN" | "OPERATOR"
    parties: list[Party]
    party_keys: frozenset[str]
    # None means "no explicit Metal Flow mapping -> fall back to each flow
    # sector's own party column", exactly like legacy's flowSectorKeys=null.
    flow_sector_keys: frozenset[str] | None
    unrestricted: bool = field(default=False)


def resolve_scope(db: Session, user: User) -> UserScope:
    """Legacy getUserScope_(). `user` is None-safe upstream (routers/auth.py)."""
    is_admin = user.role == UserRole.ADMIN and not user.admin_denied

    if is_admin:
        all_parties = sector_repo.list_parties(db)
        return UserScope(
            email=user.email,
            display_name=user.display_name or user.email,
            is_admin=True,
            role="ADMIN",
            parties=all_parties,
            party_keys=frozenset(p.party_key for p in all_parties),
            flow_sector_keys=None,
            unrestricted=True,
        )

    parties = [s.party for s in user.party_scopes if s.party is not None]
    flow_scope_rows = user.flow_scopes
    flow_sector_keys = (
        frozenset(s.flow_sector.sector_key for s in flow_scope_rows if s.flow_sector is not None)
        if flow_scope_rows
        else None
    )

    return UserScope(
        email=user.email,
        display_name=user.display_name or user.email,
        is_admin=False,
        role="OPERATOR",
        parties=parties,
        party_keys=frozenset(p.party_key for p in parties),
        flow_sector_keys=flow_sector_keys,
        unrestricted=False,
    )


def scope_allows(scope: UserScope, party_key: str | None) -> bool:
    """Legacy scopeAllows_()."""
    if scope.unrestricted:
        return True
    if not party_key:
        return False
    return party_key in scope.party_keys


def scope_allows_flow(scope: UserScope, sector_key: str, party_key: str | None) -> bool:
    """
    Legacy scopeAllowsFlow_(). An explicit flow_sector_keys mapping wins;
    otherwise falls back to the sector's own party.
    """
    if scope.unrestricted:
        return True
    if scope.flow_sector_keys is not None:
        return sector_key in scope.flow_sector_keys
    return scope_allows(scope, party_key)


def scoped_allocation_sectors(db: Session, scope: UserScope) -> list[AllocationSector]:
    """Legacy scopedSectorNames_().allocation."""
    sectors = sector_repo.list_allocation_sectors(db)
    if scope.unrestricted:
        return sectors
    return [s for s in sectors if scope_allows(scope, s.party.party_key if s.party else None)]


def scoped_flow_sectors(db: Session, scope: UserScope) -> list[FlowSector]:
    """Legacy scopedSectorNames_().flow."""
    sectors = sector_repo.list_flow_sectors(db)
    if scope.unrestricted:
        return sectors
    return [
        s for s in sectors
        if scope_allows_flow(scope, s.sector_key, s.party.party_key if s.party else None)
    ]


def apply_scope_to_allocation_model(model: AllocationModel, scope: UserScope) -> None:
    """
    Legacy applyScopeToAllocationModel_() (StagingService.gs's Phase 5C
    section — scope filtering for every read path). Trims a Daily Allocation
    model to the caller's party and marks Alloted/Balance read-only for an
    operator; the cross-party totals are removed entirely since they
    describe metal that is not theirs.
    """
    from rmas.services.validation_service import compute_totals, round3

    model.role = scope.role
    model.parties = scope.parties
    model.is_operator = not scope.is_admin

    if scope.unrestricted:
        model.can_edit_required = not model.is_saved
        model.can_edit_alloted = not model.is_saved
        model.can_edit_acquired = not model.is_saved
        model.show_global_totals = True
        return

    model.allocations = [a for a in model.allocations if scope_allows(scope, a.party_key)]
    model.metal_flow = [f for f in model.metal_flow if scope_allows_flow(scope, f.sector_key, f.party_key)]

    # Operators enter requirement and acquired metal but never allocate.
    model.can_edit_required = not model.is_saved
    model.can_edit_acquired = not model.is_saved
    model.can_edit_alloted = False
    model.show_global_totals = False

    model.totals = compute_totals(model.allocations, model.metal_flow)
    model.totals.remaining_to_allocate = Decimal("0")  # not an operator concept
    model.total_previous_acquired = round3(sum((f.previous_acquired for f in model.metal_flow), Decimal("0")))
