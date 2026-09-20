"""
models/user.py
Royal Metal Allocation System — Python port

Replaces Config.gs's ADMIN_EMAILS / NON_ADMIN_EMAILS / USER_DISPLAY_NAMES /
OPERATOR_PARTIES / OPERATOR_FLOW_SECTORS.

`admin_denied` mirrors the legacy NON_ADMIN_EMAILS deny list, which always wins
over an admin grant (CLAUDE.md section 6, rule 9). Note it only ever suppressed
*admin status* in legacy — it never blocked login.

`password_hash` is an addition to the supplied schema.sql, which predates the
2026-09-20 switch to username/password login (CLAUDE.md section 6, rule 11).
There is no signup page; it is only ever set by create_user.py.

SCOPE — the null-fallback rule, ported from StagingService.gs:
  getUserScope_() returns flowSectorKeys: null when an operator has no entry in
  OPERATOR_FLOW_SECTORS, and scopeAllowsFlow_() then falls back to matching on
  the sector's party. So ZERO rows in user_flow_scope means "derive flow access
  from party", NOT "no flow access". Do not treat an empty grant list as a deny.
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AppUser(Base):
    __tablename__ = "app_user"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_admin: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="ck_app_user_is_admin"),
        nullable=False,
        server_default=text("0"),
    )
    admin_denied: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="ck_app_user_admin_denied"),
        nullable=False,
        server_default=text("0"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="ck_app_user_is_active"),
        nullable=False,
        server_default=text("1"),
    )
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))")
    )


class UserPartyScope(Base):
    """Which parties an operator may see. An admin is unrestricted and has no rows."""

    __tablename__ = "user_party_scope"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("app_user.user_id", ondelete="CASCADE"), primary_key=True
    )
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("party.party_id", ondelete="CASCADE"), primary_key=True
    )


class UserFlowScope(Base):
    """Explicit flow-sector grants. ABSENT means fall back to the party — see the
    module docstring. An empty grant list is not a deny."""

    __tablename__ = "user_flow_scope"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("app_user.user_id", ondelete="CASCADE"), primary_key=True
    )
    flow_sector_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("flow_sector.flow_sector_id", ondelete="CASCADE"),
        primary_key=True,
    )
