"""
flow_repo.py — Metal Flow Master (FlowRecord) queries and writes.
The only place this table is touched.

Legacy: DataService.gs's readFlowMasterRows_(), buildFlowRowValues_(),
appendBothMasters_() (the flow half), deleteRowsForDate_() (flow half).
"""

from datetime import date as date_

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from rmas.models.flow import FlowRecord
from rmas.models.sector import FlowSector


def get_for_date(db: Session, flow_date: date_) -> dict[str, FlowRecord]:
    rows = db.scalars(
        select(FlowRecord)
        .options(selectinload(FlowRecord.flow_sector).selectinload(FlowSector.party))
        .where(FlowRecord.flow_date == flow_date)
    )
    return {r.flow_sector.sector_key: r for r in rows}


def exists_for_date(db: Session, flow_date: date_) -> bool:
    return db.scalar(
        select(func.count()).select_from(FlowRecord).where(FlowRecord.flow_date == flow_date)
    ) > 0


def latest_date_before(db: Session, before_date: date_) -> date_ | None:
    return db.scalar(select(func.max(FlowRecord.flow_date)).where(FlowRecord.flow_date < before_date))


def insert_rows(db: Session, rows: list[FlowRecord]) -> int:
    db.add_all(rows)
    db.flush()
    return len(rows)


def delete_for_date(db: Session, flow_date: date_) -> list[FlowRecord]:
    rows = list(db.scalars(select(FlowRecord).where(FlowRecord.flow_date == flow_date)))
    db.execute(delete(FlowRecord).where(FlowRecord.flow_date == flow_date))
    db.flush()
    return rows


def list_for_history(
    db: Session,
    *,
    date_from: date_ | None,
    date_to: date_ | None,
    sector_keys: list[str] | None,
    party_keys: frozenset[str] | None,
) -> list[FlowRecord]:
    """Legacy getMetalFlowHistory()'s row fetch."""
    stmt = select(FlowRecord).options(
        selectinload(FlowRecord.flow_sector).selectinload(FlowSector.party)
    )
    if date_from:
        stmt = stmt.where(FlowRecord.flow_date >= date_from)
    if date_to:
        stmt = stmt.where(FlowRecord.flow_date <= date_to)
    if sector_keys:
        stmt = stmt.join(FlowRecord.flow_sector).where(FlowSector.sector_key.in_(sector_keys))

    rows = list(db.scalars(stmt))
    if party_keys is not None:
        rows = [r for r in rows if r.flow_sector.party and r.flow_sector.party.party_key in party_keys]
    return rows
