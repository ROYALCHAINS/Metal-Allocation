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
from repository.sector_repo import get_flow_sector_names, get_party_names
from repository.user_repo import get_user_by_email
from routers.deps import get_current_scope, get_current_user
from schemas.auth import AccessDiagnosticsResponse, CurrentUserResponse, LoginRequest
from services.password_service import verify_password
from services.scope_service import UserScope, diagnose_access, is_administrator

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


@router.get("/access-diagnostics", response_model=AccessDiagnosticsResponse)
def access_diagnostics(
    user: AppUser = Depends(get_current_user),
    scope: UserScope = Depends(get_current_scope),
    db: Session = Depends(get_db),
) -> AccessDiagnosticsResponse:
    """Why this caller's access is what it is. Ports diagnoseAdminAccess().

    Gated by get_current_user, NOT require_admin: the question it answers is
    "why can't I see the Audit Log", which only a non-administrator ever asks.
    Gating it on admin would refuse precisely the people who need it.

    It takes NO parameters. Legacy's debugScreenFlags let an administrator
    inspect another user; that is "any other account's scope" and rule 10
    forbids it, so the subject is always the caller.
    """
    diagnosis = diagnose_access(
        user,
        scope,
        party_names=get_party_names(db, scope.party_ids),
        flow_sector_names=(
            get_flow_sector_names(db, scope.flow_sector_ids)
            if scope.flow_sector_ids is not None
            else []
        ),
    )
    return AccessDiagnosticsResponse(
        email=diagnosis.email,
        display_name=diagnosis.display_name,
        is_administrator=diagnosis.is_administrator,
        admin_denied=diagnosis.admin_denied,
        is_active=diagnosis.is_active,
        parties=list(diagnosis.party_names),
        flow_scope=diagnosis.flow_scope,
        diagnosis=list(diagnosis.diagnosis),
    )
