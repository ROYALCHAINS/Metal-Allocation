"""
repository/sector_repo.py
Royal Metal Allocation System — Python port

Reads the reference tables. Scope is applied **in the WHERE clause**, never by
fetching everything and filtering afterwards (DATABASE_OVERVIEW.md: "Scope is
applied in the WHERE clause on every query"; CLAUDE.md section 6, rule 8).

An administrator is unrestricted and sees every sector. An operator sees only
sectors belonging to the parties granted to them in `user_party_scope`.
"""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from models.party import Party
from models.sector import FlowSector, Sector
from services.scope_service import UserScope


def _restrict_to_scope(stmt: Select, party_column, scope: UserScope) -> Select:
    """Narrow a query to the parties this user may see.

    An operator with no granted parties gets an empty result, not everything —
    the filter is applied even when the grant list is empty, so a
    misconfigured account fails closed.
    """
    if scope.unrestricted:
        return stmt
    return stmt.where(party_column.in_(scope.party_ids))


def get_allocation_sectors(db: Session, scope: UserScope) -> list[tuple[Sector, Party]]:
    stmt = (
        select(Sector, Party)
        .join(Party, Party.party_id == Sector.party_id)
        .where(Sector.is_active.is_(True))
        .order_by(Sector.priority, Sector.display_order)
    )
    return list(db.execute(_restrict_to_scope(stmt, Sector.party_id, scope)).all())


def get_flow_sectors(db: Session, scope: UserScope) -> list[tuple[FlowSector, Party]]:
    """Flow sectors visible to this user.

    Note the flow-specific rule from StagingService.gs's scopeAllowsFlow_(): an
    explicit `user_flow_scope` grant list wins, and only when there is none does
    access fall back to the sector's party. `scope.flow_sector_ids` is None in
    that fallback case — see services/scope_service.py.
    """
    stmt = (
        select(FlowSector, Party)
        .join(Party, Party.party_id == FlowSector.party_id)
        .where(FlowSector.is_active.is_(True))
        .order_by(FlowSector.display_order)
    )

    if scope.unrestricted:
        return list(db.execute(stmt).all())

    if scope.flow_sector_ids is not None:
        stmt = stmt.where(FlowSector.flow_sector_id.in_(scope.flow_sector_ids))
    else:
        stmt = stmt.where(FlowSector.party_id.in_(scope.party_ids))

    return list(db.execute(stmt).all())


def get_all_party_ids(db: Session) -> list[int]:
    return list(db.scalars(select(Party.party_id).where(Party.is_active.is_(True))))


def get_party_by_key(db: Session, party_key: str) -> Party | None:
    return db.scalar(select(Party).where(Party.party_key == party_key))


def get_party_names(db: Session, party_ids: frozenset[int]) -> list[str]:
    """Names for a set of party ids, ordered so the output is stable.

    Only ever called with the CALLER'S OWN scope — never to enumerate parties
    the caller may not see (CLAUDE.md section 6, rule 10).
    """
    if not party_ids:
        return []
    return list(
        db.scalars(
            select(Party.party_name)
            .where(Party.party_id.in_(party_ids))
            .order_by(Party.party_name)
        )
    )


def get_flow_sector_names(db: Session, flow_sector_ids: frozenset[int]) -> list[str]:
    """Names for a set of EXPLICIT flow-sector grants.

    Reached only when an operator has rows in user_flow_scope. No live account
    does today — every user falls back to their party instead — so this is
    written for the branch rather than exercised by it. An empty set here means
    "the caller had no explicit grants", which is NOT the same as "no access":
    see models/user.py's null-fallback rule.
    """
    if not flow_sector_ids:
        return []
    return list(
        db.scalars(
            select(FlowSector.sector_name)
            .where(FlowSector.flow_sector_id.in_(flow_sector_ids))
            .order_by(FlowSector.display_order)
        )
    )


def get_all_sectors(db: Session) -> list[Sector]:
    """Every allocation sector, UNSCOPED.

    For naming rows in an audit snapshot and for the forward cascade, both of
    which describe the ledger rather than one user's view of it. Scope decides
    what a person may SEE; it must not decide what a historical record says or
    which rows a recalculation corrects.
    """
    return list(db.scalars(select(Sector).order_by(Sector.display_order, Sector.sector_id)))
