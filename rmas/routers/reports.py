"""
routers/reports.py — HTTP layer only. Legacy: ReportService.gs's public
endpoints. All read-only.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rmas.database import get_db
from rmas.schemas.report import (
    AllocationHistoryOut,
    DashboardSummaryOut,
    FlowHistoryOut,
    HistoryFilterOptionsOut,
    HistoryFilters,
)
from rmas.services import report_service
from rmas.services.scope_service import UserScope

from .deps import get_current_scope

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/filter-options", response_model=HistoryFilterOptionsOut)
def get_history_filter_options(db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)) -> HistoryFilterOptionsOut:
    return report_service.get_history_filter_options(db, scope)


@router.post("/allocation-history", response_model=AllocationHistoryOut)
def get_allocation_history(
    filters: HistoryFilters, db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> AllocationHistoryOut:
    return report_service.get_allocation_history(db, scope, filters)


@router.post("/flow-history", response_model=FlowHistoryOut)
def get_metal_flow_history(
    filters: HistoryFilters, db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> FlowHistoryOut:
    return report_service.get_metal_flow_history(db, scope, filters)


@router.post("/dashboard", response_model=DashboardSummaryOut)
def get_dashboard_summary(
    filters: HistoryFilters, db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> DashboardSummaryOut:
    return report_service.get_dashboard_summary(db, scope, filters)
