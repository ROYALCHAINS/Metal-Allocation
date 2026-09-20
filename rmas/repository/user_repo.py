"""repository/user_repo.py — the only place SQLAlchemy touches the user tables."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.user import AppUser, UserFlowScope, UserPartyScope


def get_user_by_email(db: Session, email: str) -> AppUser | None:
    normalized = email.strip().lower()
    return db.scalar(select(AppUser).where(AppUser.email == normalized))


def get_user_by_id(db: Session, user_id: int) -> AppUser | None:
    return db.get(AppUser, user_id)


def get_party_ids_for_user(db: Session, user_id: int) -> list[int]:
    """The parties an operator may see. Empty for an admin, who is unrestricted."""
    return list(
        db.scalars(select(UserPartyScope.party_id).where(UserPartyScope.user_id == user_id))
    )


def get_flow_sector_ids_for_user(db: Session, user_id: int) -> list[int]:
    """Explicit flow-sector grants.

    An EMPTY list means "fall back to the sector's party", not "no access" —
    legacy's getUserScope_() returns flowSectorKeys: null in that case and
    scopeAllowsFlow_() then matches on party. See models/user.py.
    """
    return list(
        db.scalars(
            select(UserFlowScope.flow_sector_id).where(UserFlowScope.user_id == user_id)
        )
    )
