"""
routers/diagnostics.py — HTTP layer only. Reduced-scope ports of
DiagnosticsService.gs / VersionCheck.gs (see services/diagnostics_service.py
docstring). /version is unauthenticated (matches legacy's version check
being safe to run from the editor); the other two are admin-only.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rmas.database import get_db
from rmas.schemas.diagnostics import ScopePreviewOut, SchemaInspectionOut, VersionInfoOut
from rmas.services import diagnostics_service
from rmas.services.scope_service import UserScope

from .deps import get_current_scope

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/version", response_model=VersionInfoOut)
def get_version_info(db: Session = Depends(get_db)) -> VersionInfoOut:
    return diagnostics_service.get_version_info(db)


@router.get("/schema", response_model=SchemaInspectionOut)
def describe_schema(db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)) -> SchemaInspectionOut:
    return diagnostics_service.describe_schema(db, scope.is_admin)


@router.get("/scope-preview", response_model=ScopePreviewOut)
def preview_scope_for(
    email: str = Query(...), db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> ScopePreviewOut:
    return diagnostics_service.preview_scope_for(db, scope.is_admin, email)
