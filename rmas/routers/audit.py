"""
routers/audit.py — HTTP layer only. Legacy: AuditReportService.gs's public
endpoints. Admin-only everywhere except get_date_revision_summary, which is
safe for every user (counts/timestamps only, never a snapshot) exactly as
legacy's getDateRevisionSummary() has no admin gate.
"""

from datetime import date as date_

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rmas.database import get_db
from rmas.schemas.audit import AuditEntryDetailOut, AuditFilterOptionsOut, AuditFilters, AuditLogOut, DateRevisionSummaryOut
from rmas.services import audit_service
from rmas.services.scope_service import UserScope

from .deps import get_current_scope

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/filter-options", response_model=AuditFilterOptionsOut)
def get_audit_filter_options(db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)) -> AuditFilterOptionsOut:
    return audit_service.get_filter_options(db, scope.is_admin)


@router.post("/log", response_model=AuditLogOut)
def get_audit_log(
    filters: AuditFilters, db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> AuditLogOut:
    return audit_service.get_audit_log(db, scope.is_admin, filters)


@router.get("/entries/{audit_id}", response_model=AuditEntryDetailOut)
def get_audit_entry_detail(
    audit_id: str, db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> AuditEntryDetailOut:
    return audit_service.get_audit_entry_detail(db, scope.is_admin, audit_id)


@router.get("/revisions/{allocation_date}", response_model=DateRevisionSummaryOut)
def get_date_revision_summary(allocation_date: date_, db: Session = Depends(get_db)) -> DateRevisionSummaryOut:
    return audit_service.get_date_revision_summary(db, allocation_date)
