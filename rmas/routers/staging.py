"""
routers/staging.py
Royal Metal Allocation System — Python port of StagingService.gs's write path

Stage 1 of the two-stage workflow: operators submit, administrators commit.
Nothing here touches the masters.

HTTP concerns only — the rules live in services/staging_service.py, which never
imports HTTPException (CLAUDE.md section 2).
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.user import AppUser
from repository.sector_repo import get_all_party_ids
from repository.user_repo import get_flow_sector_ids_for_user, get_party_ids_for_user
from routers.deps import get_current_user
from schemas.staging import SubmitRequirementRequest, SubmitRequirementResponse
from services.exceptions import (
    DuplicateRequestError,
    NotAuthorizedError,
    RmasError,
    ScopeError,
    ValidationError,
)
from services.scope_service import build_scope
from services.staging_service import submit_requirements
from services.weight_service import grams_to_kg

router = APIRouter(prefix="/staging", tags=["staging"])

_STATUS = {
    DuplicateRequestError: 409,
    NotAuthorizedError: 403,
    ScopeError: 403,
    ValidationError: 400,
}


def _http_error(exc: RmasError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(type(exc), 400),
        detail={"code": exc.code, "message": exc.message},
    )


def _resolve_scope(db: Session, user: AppUser):
    return build_scope(
        user,
        party_ids=get_party_ids_for_user(db, user.user_id),
        flow_sector_ids=get_flow_sector_ids_for_user(db, user.user_id),
        all_party_ids=get_all_party_ids(db),
    )


@router.post("/{allocation_date}", response_model=SubmitRequirementResponse)
def submit_for_date(
    allocation_date: date,
    payload: SubmitRequirementRequest,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubmitRequirementResponse:
    """Submit this party's requirement and acquisition for a date.

    One shot: once a party has submitted for a date it cannot submit again, and
    a corrected figure has to go through the administrator. Scope is resolved
    here from the session, never taken from the payload — the client sends
    weights keyed by sector id and nothing else.
    """
    try:
        result = submit_requirements(
            db,
            user=user,
            scope=_resolve_scope(db, user),
            selected=allocation_date,
            submitted_allocations=payload.allocations,
            submitted_flow=payload.metal_flow,
            request_id=payload.request_id,
        )
    except RmasError as exc:
        raise _http_error(exc) from exc

    return SubmitRequirementResponse(
        allocation_date=result.allocation_date,
        submission_id=result.submission_id,
        allocation_records=result.allocation_records,
        flow_records=result.flow_records,
        total_required_kg=grams_to_kg(result.total_required_g),
        total_acquired_kg=grams_to_kg(result.total_acquired_g),
        audit_id=result.audit_id,
    )
