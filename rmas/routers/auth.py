"""
routers/auth.py — HTTP layer only. Legacy: getCurrentUserAccess().
"""

from fastapi import APIRouter, Depends

from rmas.schemas.auth import CurrentUserOut
from rmas.services.scope_service import UserScope

from .deps import get_current_scope

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentUserOut)
def get_current_user_access(scope: UserScope = Depends(get_current_scope)) -> CurrentUserOut:
    return CurrentUserOut(email=scope.email, display_name=scope.display_name, is_admin=scope.is_admin, role=scope.role)
