"""
routers/sectors.py
Royal Metal Allocation System — Python port

Returns the reference data the caller is allowed to see. An operator mapped to
party "Royal Chain" gets only Royal Chain's sectors; an administrator gets all
of them.

The client never says which party it wants — scope is resolved server-side from
the authenticated identity on every request, and applied in SQL (CLAUDE.md
section 6, rule 8).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.user import AppUser
from repository.sector_repo import get_all_party_ids, get_allocation_sectors, get_flow_sectors
from repository.user_repo import get_flow_sector_ids_for_user, get_party_ids_for_user
from routers.deps import get_current_user
from schemas.sector import AllocationSectorResponse, FlowSectorResponse, SectorsResponse
from services.scope_service import build_scope

router = APIRouter(prefix="/sectors", tags=["sectors"])


@router.get("", response_model=SectorsResponse)
def list_sectors(
    user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> SectorsResponse:
    scope = build_scope(
        user,
        party_ids=get_party_ids_for_user(db, user.user_id),
        flow_sector_ids=get_flow_sector_ids_for_user(db, user.user_id),
        all_party_ids=get_all_party_ids(db),
    )

    return SectorsResponse(
        allocation_sectors=[
            AllocationSectorResponse(
                sector_id=sector.sector_id,
                sector_name=sector.sector_name,
                priority=sector.priority,
                purity=sector.purity,
                party_name=party.party_name,
                display_order=sector.display_order,
            )
            for sector, party in get_allocation_sectors(db, scope)
        ],
        flow_sectors=[
            FlowSectorResponse(
                flow_sector_id=sector.flow_sector_id,
                sector_name=sector.sector_name,
                party_name=party.party_name,
                display_order=sector.display_order,
            )
            for sector, party in get_flow_sectors(db, scope)
        ],
    )
