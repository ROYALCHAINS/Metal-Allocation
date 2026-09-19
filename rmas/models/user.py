"""
user.py — identity, role and scope. Replaces Config.gs's ADMIN_EMAILS /
NON_ADMIN_EMAILS / USER_DISPLAY_NAMES / OPERATOR_PARTIES /
OPERATOR_FLOW_SECTORS, and StagingService.gs's getUserScope_().

DECISION NOTE (this port): the legacy system hard-coded these mappings in
Config.gs. CLAUDE.md 6.15 already requires sector/party names to be data, not
code; the same reasoning applies to who-can-see-what, so it is modelled as
data here too rather than re-hard-coding email lists in config.py. The
business RULE — an explicit deny always overrides an admin grant
(CLAUDE.md 6.9) — is preserved exactly via `admin_denied`, resolved in
services/scope_service.py, not here.

Authentication is Google OAuth / Workspace SSO: `email` is the verified
identity from the Google ID token, matched case-insensitively as in legacy
(emailInList_ trims and lowercases).
"""

import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rmas.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lowercase/trimmed; comparisons are always case-insensitive,
    # mirroring emailInList_'s trim+lowercase behaviour.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False, length=20), default=UserRole.OPERATOR)

    # An explicit deny always overrides an admin grant (CLAUDE.md 6.9),
    # regardless of `role`. Resolved as: is_admin = (role == ADMIN) and not
    # admin_denied.
    admin_denied: Mapped[bool] = mapped_column(Boolean, default=False)

    party_scopes: Mapped[list["UserPartyScope"]] = relationship(back_populates="user")
    flow_scopes: Mapped[list["UserFlowScope"]] = relationship(back_populates="user")


class UserPartyScope(Base):
    """An operator's allowed parties. Legacy: CONFIG.OPERATOR_PARTIES."""

    __tablename__ = "user_party_scope"
    __table_args__ = (UniqueConstraint("user_id", "party_id", name="uq_user_party_scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"))

    user = relationship("User", back_populates="party_scopes")
    party = relationship("Party")


class UserFlowScope(Base):
    """
    An operator's allowed Metal Flow sectors. Legacy: CONFIG.OPERATOR_FLOW_SECTORS.

    Absence of ANY row for a user is meaningful and distinct from an empty
    list: it means "fall back to the flow sector's own Party column", exactly
    as scopeAllowsFlow_ falls back to scopeAllows_ when flowSectorKeys is
    null. services/scope_service.py must preserve that three-way distinction.
    """

    __tablename__ = "user_flow_scope"
    __table_args__ = (UniqueConstraint("user_id", "flow_sector_id", name="uq_user_flow_scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    flow_sector_id: Mapped[int] = mapped_column(ForeignKey("flow_sectors.id"))

    user = relationship("User", back_populates="flow_scopes")
    flow_sector = relationship("FlowSector")
