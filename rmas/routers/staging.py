"""
routers/staging.py — HTTP layer only. Legacy: StagingService.gs's public
endpoints (getOperatorRequirementForDate, submitOperatorRequirements,
getStagedRequirementsForDate).
"""

from datetime import date as date_

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rmas.database import get_db
from rmas.schemas.staging import (
    OperatorRequirementOut,
    StagedRequirementsOut,
    SubmitRequirementRequest,
    SubmitRequirementResultOut,
)
from rmas.services import staging_service
from rmas.services.scope_service import UserScope

from .deps import get_current_scope

router = APIRouter(prefix="/staging", tags=["staging"])


@router.get("/{selected_date}", response_model=OperatorRequirementOut)
def get_operator_requirement_for_date(
    selected_date: date_, db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> OperatorRequirementOut:
    return staging_service.get_operator_requirement_for_date(db, scope, selected_date)


@router.post("/submit", response_model=SubmitRequirementResultOut)
def submit_operator_requirements(
    payload: SubmitRequirementRequest, db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> SubmitRequirementResultOut:
    return staging_service.submit_operator_requirements(db, scope.email, scope, payload)


@router.get("/{selected_date}/admin-view", response_model=StagedRequirementsOut)
def get_staged_requirements_for_date(
    selected_date: date_, db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)
) -> StagedRequirementsOut:
    return staging_service.get_staged_requirements_for_date(db, scope.is_admin, selected_date)
