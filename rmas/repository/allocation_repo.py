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


def all_saved_dates(db: Session) -> list[str]:
    """Every date with allocation rows, ascending.

    The cascade needs the WHOLE list, not just dates after the edited one: the
    carry-forward fallback looks for the latest saved date before a given date,
    which can reach back behind the edited date through a gap.
    """
    return list(
        db.scalars(
            select(MetalMaster.allocation_date)
            .distinct()
            .order_by(MetalMaster.allocation_date)
        )
    )


def saved_dates_after(db: Session, allocation_date: str) -> list[str]:
    """Saved dates strictly after this one, ascending — the cascade's walk order."""
    return list(
        db.scalars(
            select(MetalMaster.allocation_date)
            .distinct()
            .where(MetalMaster.allocation_date > allocation_date)
            .order_by(MetalMaster.allocation_date)
        )
    )


def get_rows_for_dates(db: Session, allocation_dates: list[str]) -> list[MetalMaster]:
    """Every row across several dates, in one query.

    A cascade over thirty dates would otherwise be thirty round trips. Ordered
    so the caller can group without sorting.
    """
    if not allocation_dates:
        return []
    return list(
        db.scalars(
            select(MetalMaster)
            .where(MetalMaster.allocation_date.in_(allocation_dates))
            .order_by(MetalMaster.allocation_date, MetalMaster.sector_id)
        )
    )


def apply_recalculation(
    db: Session,
    allocation_date: str,
    updates: dict[int, tuple[int, int]],
    *,
    revision_number: int,
) -> int:
    """Update previous_requirement and balance in place for one cascaded date.

    `updates` maps sector_id -> (previous_requirement_g, balance_g).

    IN PLACE, deliberately — unlike the edited date, which is replaced wholesale
    by delete_rows_for_date() + insert_rows(). The cascade changes exactly two
    figures; everything else on the row must survive untouched, and
    priority_snapshot/purity_snapshot especially so, because they record what
    applied ON that date rather than what applies now. Rewriting the row would
    mean reconstructing those from the deleted copy — strictly more work, and
    one careless line away from substituting today's sector definitions into
    a historical record.

    It also avoids the delete-then-insert ordering hazard entirely: both write
    helpers only flush(), so inserting before deleting inside one transaction
    trips uq_master_date_sector.
    """
    if not updates:
        return 0

    changed = 0
    for row in get_rows_for_date(db, allocation_date):
        recomputed = updates.get(row.sector_id)
        if recomputed is None:
            continue
        row.previous_requirement_g, row.balance_g = recomputed
        row.revision_number = revision_number
        changed += 1

    db.flush()
    return changed
