"""
allocation_repo.py — Metal Master (AllocationRecord) queries and writes.
The only place this table is touched.

Legacy: DataService.gs's readMasterRows_(), buildMasterRowValues_(),
appendBothMasters_() (the allocation half), deleteRowsForDate_(),
dateExistsInMaster_(), latestDateKeyBefore_(), indexByDateAndSector_().

Bulk operations only, mirroring the legacy "no row-by-row operations" rule —
here that means set-based SQL instead of a Sheets bulk range write, not a
literal row count.
"""

from datetime import date as date_

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from rmas.models.allocation import AllocationRecord
from rmas.models.sector import AllocationSector


def get_for_date(db: Session, allocation_date: date_) -> dict[str, AllocationRecord]:
    """Legacy indexByDateAndSector_() for one date. Keyed by sector_key."""
    rows = db.scalars(
        select(AllocationRecord)
        .options(selectinload(AllocationRecord.sector).selectinload(AllocationSector.party))
        .where(AllocationRecord.allocation_date == allocation_date)
    )
    return {r.sector.sector_key: r for r in rows}


def exists_for_date(db: Session, allocation_date: date_) -> bool:
    """Legacy dateExistsInMaster_()."""
    return db.scalar(
        select(func.count()).select_from(AllocationRecord).where(
            AllocationRecord.allocation_date == allocation_date
        )
    ) > 0


def latest_date_before(db: Session, before_date: date_) -> date_ | None:
    """Legacy latestDateKeyBefore_() — most recent saved date strictly before the given one."""
    return db.scalar(
        select(func.max(AllocationRecord.allocation_date)).where(
            AllocationRecord.allocation_date < before_date
        )
    )


def insert_rows(db: Session, rows: list[AllocationRecord]) -> int:
    """Legacy appendBothMasters_() (allocation half). Caller commits/rolls back."""
    db.add_all(rows)
    db.flush()
    return len(rows)


def delete_for_date(db: Session, allocation_date: date_) -> list[AllocationRecord]:
    """
    Legacy deleteRowsForDate_() (allocation half), used only by
    reviseDailyAllocation. Returns the removed ORM instances (detached from
    the session's identity map after flush) so the caller can restore them
    on failure, matching legacy's compensating-rollback behaviour.
    """
    rows = list(
        db.scalars(select(AllocationRecord).where(AllocationRecord.allocation_date == allocation_date))
    )
    db.execute(delete(AllocationRecord).where(AllocationRecord.allocation_date == allocation_date))
    db.flush()
    return rows


def list_for_history(
    db: Session,
    *,
    date_from: date_ | None,
    date_to: date_ | None,
    sector_keys: list[str] | None,
    priority_keys: list[str] | None,
    purity_keys: list[str] | None,
    party_keys: frozenset[str] | None,
) -> list[AllocationRecord]:
    """
    Legacy getAllocationHistory()'s row fetch. `party_keys=None` means
    unrestricted (admin); an empty frozenset would mean "no party at all" and
    must be handled by the caller before this is reached, exactly as
    NO_PARTY_ASSIGNED is checked before the query in ReportService.gs.
    """
    stmt = select(AllocationRecord).options(
        selectinload(AllocationRecord.sector).selectinload(AllocationSector.party)
    )
    if date_from:
        stmt = stmt.where(AllocationRecord.allocation_date >= date_from)
    if date_to:
        stmt = stmt.where(AllocationRecord.allocation_date <= date_to)
    if sector_keys:
        stmt = stmt.join(AllocationRecord.sector).where(AllocationSector.sector_key.in_(sector_keys))

    rows = list(db.scalars(stmt))

    if priority_keys:
        rows = [r for r in rows if r.priority.strip().lower() in priority_keys]
    if purity_keys:
        rows = [r for r in rows if r.purity.strip().lower() in purity_keys]
    if party_keys is not None:
        rows = [r for r in rows if r.sector.party and r.sector.party.party_key in party_keys]

    return rows
