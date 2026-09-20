"""
repository/flow_repo.py
Royal Metal Allocation System — Python port

The supply ledger (`metal_flow_master`). The only place SQLAlchemy touches it.

Note the allocation and flow ledgers resolve their carry-forward source dates
INDEPENDENTLY in legacy's buildAllocationModel_ — one may fall back to an older
date than the other — which is why this mirrors allocation_repo rather than
sharing a query with it.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.flow import MetalFlowMaster


def get_rows_for_date(db: Session, allocation_date: str) -> list[MetalFlowMaster]:
    return list(
        db.scalars(
            select(MetalFlowMaster).where(MetalFlowMaster.allocation_date == allocation_date)
        )
    )


def date_exists(db: Session, allocation_date: str) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(MetalFlowMaster)
            .where(MetalFlowMaster.allocation_date == allocation_date)
        )
        or 0
    ) > 0


def latest_date_before(db: Session, allocation_date: str) -> str | None:
    return db.scalar(
        select(func.max(MetalFlowMaster.allocation_date)).where(
            MetalFlowMaster.allocation_date < allocation_date
        )
    )


def insert_rows(db: Session, rows: list[MetalFlowMaster]) -> int:
    db.add_all(rows)
    db.flush()
    return len(rows)


def delete_rows_for_date(db: Session, allocation_date: str) -> int:
    rows = get_rows_for_date(db, allocation_date)
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)
