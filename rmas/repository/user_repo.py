"""
user_repo.py — identity, role and scope lookups.

Replaces the config-list lookups in Config.gs / AuditService.gs
(ADMIN_EMAILS, NON_ADMIN_EMAILS, USER_DISPLAY_NAMES, OPERATOR_PARTIES,
OPERATOR_FLOW_SECTORS) with database reads — see models/user.py's docstring
for why. Not part of CLAUDE.md's original five repository files; added
because Google OAuth / Workspace SSO requires a real identity+scope store
that did not exist in the sheet-based legacy system.
"""

from sqlalchemy import select
from sqlalchemy.orm import selectinload, Session

from rmas.models.user import User, UserFlowScope, UserPartyScope


def get_user_by_email(db: Session, email: str) -> User | None:
    """Case-insensitive match, mirroring emailInList_'s trim+lowercase compare."""
    normalized = email.strip().lower()
    return db.scalar(
        select(User)
        .options(
            selectinload(User.party_scopes).selectinload(UserPartyScope.party),
            selectinload(User.flow_scopes).selectinload(UserFlowScope.flow_sector),
        )
        .where(User.email == normalized)
    )


def create_user(db: Session, *, email: str, display_name: str = "") -> User:
    """
    First-seen provisioning: a Google-authenticated identity with no row yet
    is created as a plain OPERATOR with no party scope (== "no party
    assigned", same as an email absent from legacy's OPERATOR_PARTIES).
    """
    user = User(email=email.strip().lower(), display_name=display_name)
    db.add(user)
    db.flush()
    return user
