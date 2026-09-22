"""
routers/events.py
Royal Metal Allocation System — Python port

The notification feed behind the toast pop-ups: it tells an administrator that
an operator has submitted, and tells an operator that the administrator has
finalised or revised a date.

POLLING, NOT PUSH. There is no WebSocket and no SSE here, deliberately. The
whole application is a same-origin FastAPI app serving static files with no
build step and no runtime dependencies beyond the ones already pinned; adding a
persistent-connection transport for two notifications would be the largest
architectural change in the project, to carry the least data. The browser asks
every few seconds instead, which costs one indexed query per client.

WHAT EACH ROLE IS TOLD, and why it leaks nothing:

  * An administrator hears about SUBMIT_REQUIREMENT. They can already see who
    submitted, on the Daily Allocation screen's submission banner.
  * An operator hears about SAVE and REVISE. A commit is date-wide and always
    includes their sectors, so "the administrator finalised this date" is
    a fact about their own data.

NO WEIGHTS CROSS THIS BOUNDARY — a message carries a date, an action and a
name, never a figure. That is what lets an operator be told about a save
without the response having to be scope-filtered per party.

The caller's OWN actions are excluded: the operator who just submitted saw a
confirmation banner and does not need a pop-up repeating it back.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models.user import AppUser
from repository import audit_repo
from repository.user_repo import get_user_by_email
from routers.deps import get_current_user
from schemas.event import EventItem, EventsResponse
from services.audit_service import (
    ACTION_REVISE,
    ACTION_SAVE,
    ACTION_SUBMIT_REQUIREMENT,
)
from services.date_service import format_display_date
from services.scope_service import is_administrator

router = APIRouter(prefix="/events", tags=["events"])

# Which actions each role is notified about. An administrator is not told about
# their own saves (excluded as the caller) nor about another administrator's,
# which would be noise rather than news on a single-administrator roster.
_ADMIN_ACTIONS = (ACTION_SUBMIT_REQUIREMENT,)
_OPERATOR_ACTIONS = (ACTION_SAVE, ACTION_REVISE)

_KIND = {
    ACTION_SUBMIT_REQUIREMENT: "submission",
    ACTION_SAVE: "save",
    ACTION_REVISE: "revision",
}


def _display_date(iso: str | None) -> str:
    """Audit entries may legitimately carry no date (migration 0004)."""
    if not iso:
        return "an unspecified date"
    try:
        return format_display_date(date.fromisoformat(iso))
    except ValueError:
        return iso


def _message(entry, db: Session) -> str:
    """One sentence, composed here so the browser prints it verbatim.

    The actor is named by display name where there is one, falling back to the
    email — the same rule the submission banner uses, so one person is not
    called two different things on two screens.
    """
    when = _display_date(entry.allocation_date)
    actor = entry.user_email
    account = get_user_by_email(db, entry.user_email)
    if account is not None and account.display_name:
        actor = account.display_name

    if entry.action_type == ACTION_SUBMIT_REQUIREMENT:
        return f"{actor} submitted requirements for {when}."
    if entry.action_type == ACTION_SAVE:
        return f"{actor} finalised the allocation for {when}."
    return f"{actor} revised the saved allocation for {when}."


@router.get("", response_model=EventsResponse)
def poll_events(
    after: int | None = Query(
        None,
        ge=0,
        description=(
            "Highest event id already seen. Omit on the first call to take a "
            "baseline without being shown the whole history as pop-ups."
        ),
    ),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventsResponse:
    """Anything worth a toast since `after`.

    Omitting `after` returns the current cursor and NO events. That is what
    stops a page load from firing a pop-up for every historical entry: the
    browser takes a baseline first, then polls forward from it.
    """
    latest = audit_repo.latest_row_id(db)
    if after is None:
        return EventsResponse(cursor=latest, events=[])

    actions = _ADMIN_ACTIONS if is_administrator(user) else _OPERATOR_ACTIONS
    entries = audit_repo.events_after(
        db, after=after, action_types=actions, exclude_email=user.email
    )

    return EventsResponse(
        # With entries, advance only to the last one RETURNED — a burst longer
        # than the limit would otherwise be skipped past unseen. With none,
        # advance to `latest`: everything in between was filtered out for this
        # role and could never match, so leaving the cursor behind would mean
        # re-scanning the same rows on every poll forever.
        cursor=entries[-1].audit_row_id if entries else latest,
        events=[
            EventItem(
                id=entry.audit_row_id,
                kind=_KIND.get(entry.action_type, "info"),
                message=_message(entry, db),
                allocation_date=entry.allocation_date,
            )
            for entry in entries
        ],
    )
