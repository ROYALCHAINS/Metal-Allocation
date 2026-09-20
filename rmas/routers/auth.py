"""
routers/auth.py
Royal Metal Allocation System — Python port

Username/password login only (CLAUDE.md section 6, rule 11 — replaces an
earlier Google OAuth decision made and removed the same day). Closed
roster, no signup: a user must already exist in the `app_user` table, with a
password hash already set by `create_user.py`, for login to succeed.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.user import AppUser
from repository.user_repo import get_user_by_email
from routers.deps import get_current_user
from schemas.auth import CurrentUserResponse, LoginRequest
from services.password_service import verify_password
from services.scope_service import is_administrator

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_response(user: AppUser) -> CurrentUserResponse:
    return CurrentUserResponse(
        email=user.email,
        # Legacy's getDisplayName_() fell back to the email when no display
        # name was configured; display_name is nullable here for the same reason.
        display_name=user.display_name or user.email,
        role="admin" if is_administrator(user) else "operator",
    )


@router.post("/login", response_model=CurrentUserResponse)
def login(
    payload: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> CurrentUserResponse:
    user = get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        # Identical error for "no such account" and "wrong password" — never
        # reveal which one it was.
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is not active")

    request.session["user_id"] = user.user_id
    return _to_response(user)


@router.post("/logout")
def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@router.get("/me", response_model=CurrentUserResponse)
def me(user: AppUser = Depends(get_current_user)) -> CurrentUserResponse:
    return _to_response(user)
