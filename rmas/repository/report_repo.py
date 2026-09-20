"""
repository/report_repo.py
Royal Metal Allocation System — Python port

Read-only history and aggregation queries over the two ledgers.

Scope is applied **in the WHERE clause of every query**, before any filter the
client asked for, so an operator can never widen it from the browser — the same
property legacy states explicitly in getAllocationHistory()
(CLAUDE.md section 6, rule 8).
"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from models.allocation import MetalMaster
from models.flow import MetalFlowMaster
from models.party import Party
from models.sector import FlowSector, Sector
from services.scope_service import UserScope


def _apply_scope(stmt: Select, party_column, scope: UserScope) -> Select:
    if scope.unrestricted:
        return stmt
    return stmt.where(party_column.in_(scope.party_ids))


def _apply_date_range(stmt: Select, date_column, date_from: str | None, date_to: str | None):
    if date_from:
        stmt = stmt.where(date_column >= date_from)
    if date_to:
        stmt = stmt.where(date_column <= date_to)
    return stmt


def _apply_allocation_filters(
    stmt: Select,
    scope: UserScope,
    *,
    date_from=None,
    date_to=None,
    party_id=None,
    sector_id=None,
    status: str = "all",
) -> Select:
    """Scope first, then the caller's filters — never the other way round."""
    stmt = _apply_scope(stmt, MetalMaster.party_id, scope)
    stmt = _apply_date_range(stmt, MetalMaster.allocation_date, date_from, date_to)
    if party_id is not None:
        stmt = stmt.where(MetalMaster.party_id == party_id)
    if sector_id is not None:
        stmt = stmt.where(MetalMaster.sector_id == sector_id)

    # Balance status, per the page spec. 'pending' is balance > 0; 'cleared' is
    # balance <= 0 (a zero closing balance is a valid, expected outcome).
    if status == "pending":
        stmt = stmt.where(MetalMaster.balance_g > 0)
    elif status == "cleared":
        stmt = stmt.where(MetalMaster.balance_g <= 0)
    elif status == "allocated":
        stmt = stmt.where(MetalMaster.alloted_g > 0)
    elif status == "unallocated":
        stmt = stmt.where(MetalMaster.alloted_g == 0)
    return stmt


def allocation_history(
    db: Session, scope: UserScope, *, limit: int = 100, offset: int = 0, **filters
):
    stmt = (
        select(MetalMaster, Sector, Party)
        .join(Sector, Sector.sector_id == MetalMaster.sector_id)
        .join(Party, Party.party_id == MetalMaster.party_id)
        # Date descending, then priority/sector order — the spec's sort.
        .order_by(MetalMaster.allocation_date.desc(), Sector.priority, Sector.display_order)
    )
    stmt = _apply_allocation_filters(stmt, scope, **filters)
    return list(db.execute(stmt.limit(limit).offset(offset)).all())


def allocation_history_count(db: Session, scope: UserScope, **filters) -> int:
    stmt = _apply_allocation_filters(select(func.count()).select_from(MetalMaster), scope, **filters)
    return db.scalar(stmt) or 0


def allocation_history_summary(db: Session, scope: UserScope, **filters):
    """Aggregates over EVERY matched row, not just the current page."""
    stmt = select(
        func.count(),
        func.count(func.distinct(MetalMaster.allocation_date)),
        func.count(func.distinct(MetalMaster.sector_id)),
        func.coalesce(func.sum(MetalMaster.previous_requirement_g), 0),
        func.coalesce(func.sum(MetalMaster.today_required_g), 0),
        func.coalesce(func.sum(MetalMaster.alloted_g), 0),
        func.coalesce(func.sum(MetalMaster.balance_g), 0),
    ).select_from(MetalMaster)
    return db.execute(_apply_allocation_filters(stmt, scope, **filters)).one()


def allocation_peak_balance(db: Session, scope: UserScope, **filters):
    """The highest total closing balance on any single date in range, and when.

    Grouped per date and summed, matching the spec's "trajectory peak".
    """
    stmt = (
        select(MetalMaster.allocation_date, func.sum(MetalMaster.balance_g).label("total"))
        .group_by(MetalMaster.allocation_date)
        .order_by(func.sum(MetalMaster.balance_g).desc())
        .limit(1)
    )
    return db.execute(_apply_allocation_filters(stmt, scope, **filters)).first()


def flow_history(
    db: Session,
    scope: UserScope,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    party_id: int | None = None,
    limit: int = 500,
    offset: int = 0,
):
    stmt = (
        select(MetalFlowMaster, FlowSector, Party)
        .join(FlowSector, FlowSector.flow_sector_id == MetalFlowMaster.flow_sector_id)
        .join(Party, Party.party_id == MetalFlowMaster.party_id)
        .order_by(MetalFlowMaster.allocation_date.desc(), FlowSector.display_order)
    )
    stmt = _apply_scope(stmt, MetalFlowMaster.party_id, scope)
    stmt = _apply_date_range(stmt, MetalFlowMaster.allocation_date, date_from, date_to)
    if party_id is not None:
        stmt = stmt.where(MetalFlowMaster.party_id == party_id)
    return list(db.execute(stmt.limit(limit).offset(offset)).all())


def flow_history_count(db: Session, scope: UserScope, **filters) -> int:
    stmt = select(func.count()).select_from(MetalFlowMaster)
    stmt = _apply_scope(stmt, MetalFlowMaster.party_id, scope)
    stmt = _apply_date_range(
        stmt, MetalFlowMaster.allocation_date, filters.get("date_from"), filters.get("date_to")
    )
    if filters.get("party_id") is not None:
        stmt = stmt.where(MetalFlowMaster.party_id == filters["party_id"])
    return db.scalar(stmt) or 0


# --------------------------------------------------------------- aggregations


def _dashboard_filters(stmt: Select, scope: UserScope, date_from, date_to, sector_id):
    stmt = _apply_scope(stmt, MetalMaster.party_id, scope)
    stmt = _apply_date_range(stmt, MetalMaster.allocation_date, date_from, date_to)
    if sector_id is not None:
        stmt = stmt.where(MetalMaster.sector_id == sector_id)
    return stmt


def totals_by_date(db: Session, scope: UserScope, *, date_from=None, date_to=None, sector_id=None):
    """One row per saved date: the series behind the dashboard's trend charts."""
    stmt = (
        select(
            MetalMaster.allocation_date,
            func.sum(MetalMaster.previous_requirement_g),
            func.sum(MetalMaster.today_required_g),
            func.sum(MetalMaster.alloted_g),
            func.sum(MetalMaster.balance_g),
        )
        .group_by(MetalMaster.allocation_date)
        .order_by(MetalMaster.allocation_date)
    )
    return list(db.execute(_dashboard_filters(stmt, scope, date_from, date_to, sector_id)).all())


def acquired_by_date(
    db: Session, scope: UserScope, *, date_from=None, date_to=None, flow_sector_id=None
):
    stmt = (
        select(MetalFlowMaster.allocation_date, func.sum(MetalFlowMaster.acquired_g))
        .group_by(MetalFlowMaster.allocation_date)
        .order_by(MetalFlowMaster.allocation_date)
    )
    stmt = _apply_scope(stmt, MetalFlowMaster.party_id, scope)
    stmt = _apply_date_range(stmt, MetalFlowMaster.allocation_date, date_from, date_to)
    # Note this is a FLOW sector id, resolved by the service — the allocation
    # sector id the client sends means nothing in this table.
    if flow_sector_id is not None:
        stmt = stmt.where(MetalFlowMaster.flow_sector_id == flow_sector_id)
    return list(db.execute(stmt).all())


def present_flow_sectors(db: Session, scope: UserScope, *, date_from=None, date_to=None):
    """Flow sectors that actually carry a record in scope and range.

    The dashboard's cross-ledger rule needs to know which sector names exist on
    the supply side before it dares filter by one.
    """
    stmt = (
        select(FlowSector.flow_sector_id, FlowSector.sector_name)
        .join(MetalFlowMaster, MetalFlowMaster.flow_sector_id == FlowSector.flow_sector_id)
        .group_by(FlowSector.flow_sector_id)
    )
    stmt = _apply_scope(stmt, MetalFlowMaster.party_id, scope)
    stmt = _apply_date_range(stmt, MetalFlowMaster.allocation_date, date_from, date_to)
    return list(db.execute(stmt).all())


def totals_by_sector(
    db: Session, scope: UserScope, *, date_from=None, date_to=None, sector_id=None
):
    stmt = (
        select(
            Sector.sector_name,
            Sector.priority,
            func.sum(MetalMaster.today_required_g),
            func.sum(MetalMaster.alloted_g),
            func.sum(MetalMaster.balance_g),
        )
        .join(Sector, Sector.sector_id == MetalMaster.sector_id)
        .group_by(Sector.sector_id)
        # Required descending — the dashboard's "top 10 by demand" chart slices
        # straight off the front of this list.
        .order_by(func.sum(MetalMaster.today_required_g).desc())
    )
    return list(db.execute(_dashboard_filters(stmt, scope, date_from, date_to, sector_id)).all())


def latest_balance_by_sector(
    db: Session, scope: UserScope, *, date_from=None, date_to=None, sector_id=None
):
    """Each sector's balance on ITS OWN most recent saved date in range.

    Not a range total: balances carry forward, so summing a sector's balance
    across dates counts the same outstanding metal once per day it stayed
    outstanding. Ports legacy's topPending, which reads the latest row per
    sector.
    """
    latest = _dashboard_filters(
        select(
            MetalMaster.sector_id.label("sector_id"),
            func.max(MetalMaster.allocation_date).label("latest_date"),
        ).group_by(MetalMaster.sector_id),
        scope,
        date_from,
        date_to,
        sector_id,
    ).subquery()

    stmt = (
        select(
            Sector.sector_name,
            Sector.priority,
            MetalMaster.allocation_date,
            func.sum(MetalMaster.balance_g),
        )
        .join(Sector, Sector.sector_id == MetalMaster.sector_id)
        .join(
            latest,
            (latest.c.sector_id == MetalMaster.sector_id)
            & (latest.c.latest_date == MetalMaster.allocation_date),
        )
        # Summed because one sector on one date may carry several parties.
        .group_by(MetalMaster.sector_id)
    )
    return list(db.execute(_dashboard_filters(stmt, scope, date_from, date_to, sector_id)).all())


def totals_by_priority(
    db: Session, scope: UserScope, *, date_from=None, date_to=None, sector_id=None
):
    """Grouped by the priority LABEL, exactly as legacy does — the label is what
    users see and filter on (ReportService.gs line 587)."""
    stmt = (
        select(
            Sector.priority,
            func.sum(MetalMaster.today_required_g),
            func.sum(MetalMaster.alloted_g),
            func.sum(MetalMaster.balance_g),
        )
        .join(Sector, Sector.sector_id == MetalMaster.sector_id)
        .group_by(Sector.priority)
        .order_by(Sector.priority)
    )
    return list(db.execute(_dashboard_filters(stmt, scope, date_from, date_to, sector_id)).all())


def flow_cells(db: Session, scope: UserScope, *, date_from=None, date_to=None, sector_id=None):
    """Acquired per (date, flow sector) — the heatmap grid.

    Duplicates are summed, matching legacy's buildFlowHeatmap_() where
    `cellMap[key] = (cellMap[key] || 0) + r.acquired`.
    """
    stmt = (
        select(
            MetalFlowMaster.allocation_date,
            FlowSector.flow_sector_id,
            FlowSector.sector_name,
            func.coalesce(func.sum(MetalFlowMaster.acquired_g), 0),
        )
        .join(FlowSector, FlowSector.flow_sector_id == MetalFlowMaster.flow_sector_id)
        .group_by(MetalFlowMaster.allocation_date, FlowSector.flow_sector_id)
    )
    stmt = _apply_scope(stmt, MetalFlowMaster.party_id, scope)
    stmt = _apply_date_range(stmt, MetalFlowMaster.allocation_date, date_from, date_to)
    if sector_id is not None:
        stmt = stmt.where(MetalFlowMaster.flow_sector_id == sector_id)
    return list(db.execute(stmt).all())


def flow_summary(db: Session, scope: UserScope, *, date_from=None, date_to=None, sector_id=None):
    """Record count, distinct dates, distinct sectors and the total acquired."""
    stmt = select(
        func.count(),
        func.count(func.distinct(MetalFlowMaster.allocation_date)),
        func.count(func.distinct(MetalFlowMaster.flow_sector_id)),
        func.coalesce(func.sum(MetalFlowMaster.acquired_g), 0),
    ).select_from(MetalFlowMaster)
    stmt = _apply_scope(stmt, MetalFlowMaster.party_id, scope)
    stmt = _apply_date_range(stmt, MetalFlowMaster.allocation_date, date_from, date_to)
    if sector_id is not None:
        stmt = stmt.where(MetalFlowMaster.flow_sector_id == sector_id)
    return db.execute(stmt).one()
