"""
repository/staging_repo.py
Royal Metal Allocation System — Python port

Operator submissions awaiting an administrator's commit. Nothing here writes to
the masters — only the admin save path does (CLAUDE.md section 1).

Scope is applied in the WHERE clause of every read, before any filter the
caller asked for, exactly as in the other repositories (rule 8).
"""

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from models.sector import FlowSector, Sector
from models.staging import MetalRequirementStaging
from services.scope_service import UserScope

SUBMITTED = "SUBMITTED"
CONSUMED = "CONSUMED"


def _apply_scope(stmt: Select, scope: UserScope) -> Select:
    if scope.unrestricted:
        return stmt
    return stmt.where(MetalRequirementStaging.party_id.in_(scope.party_ids))


def submitted_rows(
    db: Session, allocation_date: str, scope: UserScope
) -> list[MetalRequirementStaging]:
    """Every still-unconsumed submission for a date, within scope."""
    stmt = select(MetalRequirementStaging).where(
        MetalRequirementStaging.allocation_date == allocation_date,
        MetalRequirementStaging.status == SUBMITTED,
    )
    return list(db.scalars(_apply_scope(stmt, scope)))


def any_rows_for_parties(
    db: Session, allocation_date: str, party_ids: frozenset[int]
) -> list[MetalRequirementStaging]:
    """Submissions for these parties on this date, AT ANY STATUS.

    Deliberately NOT filtered to SUBMITTED. Legacy's resubmission check reads
    every staging row for the date and party, so once an administrator commits
    and the rows flip to CONSUMED the party is still permanently blocked from
    submitting again for that date. Filtering to SUBMITTED here would quietly
    reopen submissions after each save — the opposite of "a submission cannot be
    changed once sent".

    Also not filtered by operator: two operators sharing a party block each
    other, because the submission is made on the party's behalf, not the
    person's.
    """
    if not party_ids:
        return []
    return list(
        db.scalars(
            select(MetalRequirementStaging).where(
                MetalRequirementStaging.allocation_date == allocation_date,
                MetalRequirementStaging.party_id.in_(party_ids),
            )
        )
    )


def staged_allocation_values(
    db: Session, allocation_date: str, scope: UserScope
) -> dict[int, int]:
    """sector_id -> submitted grams, summed if several operators contributed."""
    stmt = (
        select(
            MetalRequirementStaging.sector_id,
            func.coalesce(func.sum(MetalRequirementStaging.value_g), 0),
        )
        .where(
            MetalRequirementStaging.allocation_date == allocation_date,
            MetalRequirementStaging.status == SUBMITTED,
            MetalRequirementStaging.record_type == "ALLOCATION",
        )
        .group_by(MetalRequirementStaging.sector_id)
    )
    return {row[0]: row[1] for row in db.execute(_apply_scope(stmt, scope))}


def staged_flow_values(
    db: Session, allocation_date: str, scope: UserScope
) -> dict[int, int]:
    """flow_sector_id -> submitted grams."""
    stmt = (
        select(
            MetalRequirementStaging.flow_sector_id,
            func.coalesce(func.sum(MetalRequirementStaging.value_g), 0),
        )
        .where(
            MetalRequirementStaging.allocation_date == allocation_date,
            MetalRequirementStaging.status == SUBMITTED,
            MetalRequirementStaging.record_type == "FLOW",
        )
        .group_by(MetalRequirementStaging.flow_sector_id)
    )
    return {row[0]: row[1] for row in db.execute(_apply_scope(stmt, scope))}


def submission_summary(db: Session, allocation_date: str, scope: UserScope):
    """Who submitted for this date and when, for the administrator's screen."""
    stmt = (
        select(
            MetalRequirementStaging.operator_email,
            MetalRequirementStaging.party_id,
            func.min(MetalRequirementStaging.submitted_at),
            func.count(),
        )
        .where(
            MetalRequirementStaging.allocation_date == allocation_date,
            MetalRequirementStaging.status == SUBMITTED,
        )
        .group_by(
            MetalRequirementStaging.operator_email, MetalRequirementStaging.party_id
        )
        .order_by(func.min(MetalRequirementStaging.submitted_at))
    )
    return list(db.execute(_apply_scope(stmt, scope)).all())


def insert_rows(db: Session, rows: list[MetalRequirementStaging]) -> int:
    db.add_all(rows)
    db.flush()
    return len(rows)


def mark_consumed(db: Session, allocation_date: str) -> int:
    """Ports markStagingConsumed_(): only SUBMITTED rows are matched.

    Called when the administrator commits the date, so the submissions stop
    being pending without being deleted — the record of what was submitted is
    kept. Deliberately NOT scope-filtered: a commit consumes the whole date.
    """
    result = db.execute(
        MetalRequirementStaging.__table__.update()
        .where(
            MetalRequirementStaging.allocation_date == allocation_date,
            MetalRequirementStaging.status == SUBMITTED,
        )
        .values(status=CONSUMED)
    )
    return result.rowcount


def delete_for_date(db: Session, allocation_date: str) -> int:
    """Only for test fixtures and re-seeding. Not reachable from the API."""
    return db.execute(
        delete(MetalRequirementStaging).where(
            MetalRequirementStaging.allocation_date == allocation_date
        )
    ).rowcount


def sector_party_map(db: Session) -> dict[int, int]:
    """sector_id -> party_id. Ports part of buildSectorPartyMaps_()."""
    return {row[0]: row[1] for row in db.execute(select(Sector.sector_id, Sector.party_id))}


def flow_sector_party_map(db: Session) -> dict[int, int]:
    return {
        row[0]: row[1]
        for row in db.execute(select(FlowSector.flow_sector_id, FlowSector.party_id))
    }
