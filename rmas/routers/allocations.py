"""
routers/allocations.py
Royal Metal Allocation System — Python port

The Daily Allocation screen. HTTP wiring only; the model is assembled by
services/allocation_service.py (CLAUDE.md section 2).

Scope comes from the authenticated session on every request — an operator sees
only their party's sectors, and the client never says which party it wants
(rule 8).
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.user import AppUser
from repository.sector_repo import get_all_party_ids
from repository.user_repo import get_flow_sector_ids_for_user, get_party_ids_for_user
from routers.deps import get_current_user
from schemas.allocation import (
    AllocationModelResponse,
    AllocationRowResponse,
    FlowRowResponse,
    SaveAllocationRequest,
    SaveAllocationResponse,
    TotalsResponse,
)
from services.scope_service import is_administrator
from services.staging_service import apply_staging_to_model
from services.allocation_service import (
    AllocationModel,
    build_allocation_model,
    save_daily_allocation,
)
from services.exceptions import (
    DateAlreadySavedError,
    DuplicateRequestError,
    NotAuthorizedError,
    RmasError,
    ScopeError,
    ValidationError,
)
from services.scope_service import build_scope
from services.validation_service import Totals
from services.weight_service import grams_to_kg

router = APIRouter(prefix="/allocations", tags=["allocations"])

# Domain error -> HTTP status. Routers own this translation; services never
# import HTTPException (CLAUDE.md section 2).
_STATUS_BY_ERROR = {
    ValidationError: 400,
    NotAuthorizedError: 403,
    ScopeError: 403,
    DuplicateRequestError: 409,
    DateAlreadySavedError: 409,
}


def _http_error(exc: RmasError) -> HTTPException:
    status = _STATUS_BY_ERROR.get(type(exc), 400)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


def _totals_response(totals: Totals) -> TotalsResponse:
    return TotalsResponse(
        total_previous_requirement_kg=grams_to_kg(totals.total_previous_requirement_g),
        total_today_required_kg=grams_to_kg(totals.total_today_required_g),
        total_alloted_kg=grams_to_kg(totals.total_alloted_g),
        total_balance_kg=grams_to_kg(totals.total_balance_g),
        total_acquired_kg=grams_to_kg(totals.total_acquired_g),
        remaining_to_allocate_kg=grams_to_kg(totals.remaining_to_allocate_g),
    )


def _to_response(model: AllocationModel) -> AllocationModelResponse:
    return AllocationModelResponse(
        selected_date=model.selected_date,
        selected_date_display=model.selected_date_display,
        rule_source_date=model.rule_source_date,
        rule_source_date_display=model.rule_source_date_display,
        previous_source_date=model.previous_source_date,
        previous_source_date_display=model.previous_source_date_display,
        used_fallback_source=model.used_fallback_source,
        has_previous_data=model.has_previous_data,
        is_saved=model.is_saved,
        allocations=[
            AllocationRowResponse(
                sector_id=row.sector_id,
                sector_name=row.sector_name,
                priority=row.priority,
                purity=row.purity,
                party_name=row.party_name,
                previous_requirement_kg=grams_to_kg(row.previous_requirement_g),
                today_required_kg=grams_to_kg(row.today_required_g),
                alloted_kg=grams_to_kg(row.alloted_g),
                balance_kg=grams_to_kg(row.balance_g),
                from_submission=row.from_submission,
            )
            for row in model.allocations
        ],
        metal_flow=[
            FlowRowResponse(
                flow_sector_id=row.flow_sector_id,
                sector_name=row.sector_name,
                party_name=row.party_name,
                previous_acquired_kg=grams_to_kg(row.previous_acquired_g),
                today_acquired_kg=grams_to_kg(row.today_acquired_g),
                from_submission=row.from_submission,
            )
            for row in model.metal_flow
        ],
        totals=_totals_response(model.totals),
        total_previous_acquired_kg=grams_to_kg(model.total_previous_acquired_g),
    )


def _resolve_scope(db: Session, user: AppUser):
    return build_scope(
        user,
        party_ids=get_party_ids_for_user(db, user.user_id),
        flow_sector_ids=get_flow_sector_ids_for_user(db, user.user_id),
        all_party_ids=get_all_party_ids(db),
    )


@router.get("/{allocation_date}", response_model=AllocationModelResponse)
def get_allocation_for_date(
    allocation_date: date,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AllocationModelResponse:
    scope = _resolve_scope(db, user)
    try:
        model = build_allocation_model(db, allocation_date, scope)
        # Operator submissions overlay the model here, which is how an
        # operator's figures reach the administrator's screen. Applied after
        # the model is built and scoped, exactly as legacy orders it.
        state = apply_staging_to_model(db, model, scope, allocation_date)
    except RmasError as exc:
        raise _http_error(exc) from exc

    model.already_submitted = state.already_submitted
    model.staged_value_count = state.staged_value_count

    response = _to_response(model)
    # An operator may submit while the date is neither saved nor already
    # submitted by their party. Decided on the server; the browser is told,
    # never asked.
    response.already_submitted = state.already_submitted
    response.staged_value_count = state.staged_value_count
    response.can_submit = (
        not is_administrator(user) and not model.is_saved and not state.already_submitted
    )
    return response


@router.post("/{allocation_date}", response_model=SaveAllocationResponse)
def save_allocation_for_date(
    allocation_date: date,
    payload: SaveAllocationRequest,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SaveAllocationResponse:
    """Commit a date. Administrators only — operators submit requirements instead.

    A saved date is immutable; changing it afterwards goes through the revision
    path, which requires a written reason.
    """
    try:
        result = save_daily_allocation(
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

    return SaveAllocationResponse(
        allocation_date=result.allocation_date,
        allocation_records=result.allocation_records,
        flow_records=result.flow_records,
        audit_id=result.audit_id,
        request_id=result.request_id,
        totals=_totals_response(result.totals),
    )
