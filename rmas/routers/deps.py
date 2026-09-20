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
from repository.user_repo import get_user_by_id
from services.scope_service import is_administrator


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = get_user_by_id(db, user_id)
    if user is None:
        # The account was removed after the session was issued.
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session no longer valid")
    return user


def require_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    if not is_administrator(user):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
