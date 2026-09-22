"""
routers/deps.py
Royal Metal Allocation System — Python port

FastAPI dependency-injection helpers only — HTTP concerns (reading the
session cookie, raising HTTPException). The actual authorization decision
(is this user an administrator) lives in services/scope_service.py:
"Services never import HTTPException" (CLAUDE.md section 2).
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.user import AppUser
from repository.sector_repo import get_all_party_ids
from repository.user_repo import (
    get_flow_sector_ids_for_user,
    get_party_ids_for_user,
    get_user_by_id,
)
from services.scope_service import UserScope, build_scope, is_administrator


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = get_user_by_id(db, user_id)
    if user is None:
        # The account was removed after the session was issued.
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session no longer valid")
    if not user.is_active:
        # Deactivated AFTER the session was issued. login() refuses an inactive
        # account (routers/auth.py), but that check alone only guards the moment
        # of sign-in — without this one, deactivating somebody leaves them with
        # full access, administrator access included, until their cookie expires.
        #
        # 401 and a cleared session rather than 403, matching the branch above:
        # both are "this session is finished", and a 403 would claim the caller
        # is still authenticated while we are in the act of signing them out.
        # login() answers 403 for the same account because no session exists
        # there to end — a different question, so a different code.
        #
        # Note this makes diagnose_access()'s "marked inactive" line unreachable
        # over HTTP, since the diagnostics route also depends on this function.
        # The line stays correct and stays tested (test_scope_service.py), and
        # failing closed matters more than explaining why to a disabled account.
        request.session.clear()
        raise HTTPException(status_code=401, detail="This account is no longer active")
    return user


def require_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    if not is_administrator(user):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def get_current_scope(
    user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserScope:
    """The caller's scope, rebuilt from the database on every request (rule 8).

    Never assembled from anything the client sent. FastAPI caches
    get_current_user per request, so depending on both costs one user lookup.
    """
    return build_scope(
        user,
        party_ids=get_party_ids_for_user(db, user.user_id),
        flow_sector_ids=get_flow_sector_ids_for_user(db, user.user_id),
        all_party_ids=get_all_party_ids(db),
    )
