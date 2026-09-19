"""
diagnostics_service.py
Royal Metal Allocation System — Python port

Reduced-scope ports of DiagnosticsService.gs and VersionCheck.gs (both
Apps-Script-environment diagnostics with no direct SQL equivalent — see the
port decisions recorded in CLAUDE.md-adjacent project notes) plus
previewScopeFor() from VersionCheck.gs, which is still meaningful: an admin
confirming what the server would resolve for another user's access without
impersonating them.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from rmas.config import get_settings
from rmas.repository import allocation_repo, sector_repo, user_repo
from rmas.rules.business_rules import SECTOR_EXPECTATIONS
from rmas.schemas.diagnostics import ScopePreviewOut, SchemaInspectionOut, VersionInfoOut
from rmas.services.exceptions import NotFoundError, ScopeError
from rmas.services.scope_service import resolve_scope, scoped_allocation_sectors, scoped_flow_sectors

_settings = get_settings()


def get_version_info(db: Session) -> VersionInfoOut:
    """Legacy checkInstalledFiles() — here, confirming what's actually running."""
    try:
        db.execute(text("SELECT 1"))
        connected = True
    except Exception:  # noqa: BLE001
        connected = False
    return VersionInfoOut(
        app_name=_settings.app_name, app_version=_settings.app_version,
        database_connected=connected, app_timezone=_settings.app_timezone,
    )


def describe_schema(db: Session, is_admin: bool) -> SchemaInspectionOut:
    """SQL equivalent of describeDetectedSchema()/inspectAllLayouts()."""
    if not is_admin:
        raise ScopeError("Schema diagnostics are restricted to administrators.", code="NOT_AUTHORIZED")

    allocation_sectors = sector_repo.list_allocation_sectors(db)
    flow_sectors = sector_repo.list_flow_sectors(db)
    parties = sector_repo.list_parties(db)
    all_rows = allocation_repo.list_for_history(
        db, date_from=None, date_to=None, sector_keys=None, priority_keys=None, purity_keys=None, party_keys=None
    )
    distinct_dates = {r.allocation_date for r in all_rows}

    matches = (
        len(allocation_sectors) == SECTOR_EXPECTATIONS.allocation_rows
        and len(flow_sectors) == SECTOR_EXPECTATIONS.flow_rows
    )

    return SchemaInspectionOut(
        allocation_sector_count=len(allocation_sectors), expected_allocation_rows=SECTOR_EXPECTATIONS.allocation_rows,
        flow_sector_count=len(flow_sectors), expected_flow_rows=SECTOR_EXPECTATIONS.flow_rows,
        party_count=len(parties), distinct_saved_dates=len(distinct_dates), counts_match_expectation=matches,
    )


def preview_scope_for(db: Session, requester_is_admin: bool, target_email: str) -> ScopePreviewOut:
    """Legacy previewScopeFor(). Admin-only, since it reveals another user's scope."""
    if not requester_is_admin:
        raise ScopeError("Only an administrator can preview another user’s scope.", code="NOT_AUTHORIZED")

    user = user_repo.get_user_by_email(db, target_email)
    if user is None:
        raise NotFoundError(f'No user account exists for "{target_email}".', code="USER_NOT_FOUND")

    scope = resolve_scope(db, user)
    allocation_sectors = scoped_allocation_sectors(db, scope)
    flow_sectors = scoped_flow_sectors(db, scope)

    return ScopePreviewOut(
        email=scope.email, display_name=scope.display_name, role=scope.role, is_admin=scope.is_admin,
        parties=[p.party_name for p in scope.parties],
        allocation_sectors_visible=len(allocation_sectors), allocation_sector_names=[d.sector_name for d in allocation_sectors],
        flow_sectors_visible=len(flow_sectors), flow_sector_names=[d.sector_name for d in flow_sectors],
        can_edit_alloted=scope.is_admin, can_save_date=scope.is_admin,
    )
