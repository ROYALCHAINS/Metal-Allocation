"""
routers/allocations.py — HTTP layer only. No business logic — see
services/allocation_service.py. Legacy: Code.gs's public endpoints.
"""

from datetime import date as date_

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rmas.database import get_db
from rmas.models.user import User
from rmas.schemas.allocation import (
    AllocationModelOut,
    BootstrapOut,
    DateAlreadySavedOut,
    ReviseAllocationRequest,
    ReviseResultOut,
    SaveAllocationRequest,
    SaveResultOut,
)
from rmas.services import allocation_service
from rmas.services.scope_service import UserScope

from .deps import get_current_scope, get_current_user

router = APIRouter(prefix="/allocations", tags=["allocations"])


@router.get("/bootstrap", response_model=BootstrapOut)
def bootstrap(db: Session = Depends(get_db), scope: UserScope = Depends(get_current_scope)) -> BootstrapOut:
    return allocation_service.get_bootstrap_data(db, scope)


@router.get("/check-saved", response_model=DateAlreadySavedOut)
def check_date_already_saved(selected_date: date_, db: Session = Depends(get_db)) -> DateAlreadySavedOut:
    return allocation_service.check_date_already_saved(db, selected_date)


@router.get("/{selected_date}", response_model=AllocationModelOut)
def get_allocation_for_date(
    selected_date: date_, db: Session = Depends(get_db),
    user: User = Depends(get_current_user), scope: UserScope = Depends(get_current_scope),
) -> AllocationModelOut:
    return allocation_service.get_allocation_for_date(db, user, scope, selected_date)


@router.post("/save", response_model=SaveResultOut)
def save_daily_allocation(
    payload: SaveAllocationRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> SaveResultOut:
    return allocation_service.save_daily_allocation(db, user, payload)


@router.post("/revise", response_model=ReviseResultOut)
def revise_daily_allocation(
    payload: ReviseAllocationRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ReviseResultOut:
    return allocation_service.revise_daily_allocation(db, user, payload)
