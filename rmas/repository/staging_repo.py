"""
staging_repo.py — Metal Requirement Staging queries and writes.
The only place this table is touched.

Legacy: StagingService.gs's readStagingRows_(), the insert block inside
submitOperatorRequirements(), and markStagingConsumed_().
"""

from datetime import date as date_

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from rmas.models.staging import StagingRequirement, StagingStatus


def list_for_date(db: Session, allocation_date: date_) -> list[StagingRequirement]:
    return list(
        db.scalars(
            select(StagingRequirement)
            .options(selectinload(StagingRequirement.party))
            .where(StagingRequirement.allocation_date == allocation_date)
        )
    )


def list_submitted_for_date_and_parties(
    db: Session, allocation_date: date_, party_ids: list[int]
) -> list[StagingRequirement]:
    """Legacy's 'existing' check before inserting a new submission."""
    if not party_ids:
        return []
    return list(
        db.scalars(
            select(StagingRequirement).where(
                StagingRequirement.allocation_date == allocation_date,
                StagingRequirement.party_id.in_(party_ids),
            )
        )
    )


def insert_rows(db: Session, rows: list[StagingRequirement]) -> int:
    db.add_all(rows)
    db.flush()
    return len(rows)


def mark_consumed(db: Session, allocation_date: date_) -> int:
    """Legacy markStagingConsumed_(). Never raises — caller treats 0 as fine."""
    result = db.execute(
        update(StagingRequirement)
        .where(
            StagingRequirement.allocation_date == allocation_date,
            StagingRequirement.status == StagingStatus.SUBMITTED,
        )
        .values(status=StagingStatus.CONSUMED)
    )
    db.flush()
    return result.rowcount or 0
