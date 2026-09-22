"""schemas/event.py — the notification feed behind the toast pop-ups.

Deliberately carries NO weights. A message names a date, an action and a
person; never a figure. That is what lets an operator be told "the
administrator finalised this date" without the payload needing to be
scope-filtered per party (CLAUDE.md section 6, rule 8).
"""

from pydantic import BaseModel


class EventItem(BaseModel):
    # audit_row_id — monotonic, and the client's cursor.
    id: int
    # 'submission' | 'save' | 'revision', chosen by the server so the browser
    # picks a toast colour without interpreting the action vocabulary itself.
    kind: str
    # Composed server-side and printed verbatim.
    message: str
    allocation_date: str | None = None


class EventsResponse(BaseModel):
    # Pass back as `after` on the next poll.
    cursor: int
    events: list[EventItem]
