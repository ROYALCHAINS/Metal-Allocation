"""
repository/allocation_repo.py
Royal Metal Allocation System — Python port

The allocation ledger (`metal_master`). The only place SQLAlchemy touches it.

`allocation_date` is TEXT in 'YYYY-MM-DD', which sorts lexicographically — so
"the most recent saved date before X" is a plain indexed MAX() rather than
anything clever (schema.sql's date design note).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.allocation import MetalMaster


def get_rows_for_date(db: Session, allocation_date: str) -> list[MetalMaster]:
    return list(
        db.scalars(
            select(MetalMaster).where(MetalMaster.allocation_date == allocation_date)
        )
    )


def date_exists(db: Session, allocation_date: str) -> bool:
    """Whether this date has already been committed. Drives the
    "saved dates are immutable, revise instead" behaviour."""
    return (
        db.scalar(
            select(func.count())
            .select_from(MetalMaster)
            .where(MetalMaster.allocation_date == allocation_date)
        )
        or 0
    ) > 0


def latest_date_before(db: Session, allocation_date: str) -> str | None:
    """The most recent saved date strictly before this one.

    This is what stops a skipped day silently resetting balances to zero when
    CARRY_FORWARD_FROM_LATEST_SAVED is on (CLAUDE.md section 6, rule 5).
    """
    return db.scalar(
        select(func.max(MetalMaster.allocation_date)).where(
            MetalMaster.allocation_date < allocation_date
        )
    )


def insert_rows(db: Session, rows: list[MetalMaster]) -> int:
    db.add_all(rows)
    db.flush()
    return len(rows)


def delete_rows_for_date(db: Session, allocation_date: str) -> int:
    """Used by the revision path, which replaces a date's rows wholesale —
    matching legacy's deleteRowsForDate_() + appendBothMasters_()."""
    rows = get_rows_for_date(db, allocation_date)
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)
