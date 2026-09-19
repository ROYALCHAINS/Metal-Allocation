"""
sector_repo.py — SQLAlchemy queries for parties, allocation sectors and flow
sectors. The only place these tables are touched.

Legacy: DataService.gs's readAllocationSectorDefinitions_(),
readFlowSectorDefinitions_(), readPartyDefinitions_(). SchemaService.gs's
header-detection has no equivalent here — the schema is explicit SQL
(CLAUDE.md 6.16).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from rmas.models.party import Party
from rmas.models.sector import AllocationSector, FlowSector


def list_parties(db: Session) -> list[Party]:
    return list(db.scalars(select(Party).order_by(Party.id)))


def list_allocation_sectors(db: Session) -> list[AllocationSector]:
    """Sheet order == sort_order, matching legacy's row-order iteration."""
    return list(db.scalars(select(AllocationSector).order_by(AllocationSector.sort_order)))


def list_flow_sectors(db: Session) -> list[FlowSector]:
    return list(db.scalars(select(FlowSector).order_by(FlowSector.sort_order)))


def get_allocation_sector_by_key(db: Session, sector_key: str) -> AllocationSector | None:
    return db.scalar(select(AllocationSector).where(AllocationSector.sector_key == sector_key))


def get_flow_sector_by_key(db: Session, sector_key: str) -> FlowSector | None:
    return db.scalar(select(FlowSector).where(FlowSector.sector_key == sector_key))


def get_party_by_key(db: Session, party_key: str) -> Party | None:
    return db.scalar(select(Party).where(Party.party_key == party_key))
