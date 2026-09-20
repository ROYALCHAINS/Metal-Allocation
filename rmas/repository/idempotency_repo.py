"""
repository/idempotency_repo.py
Royal Metal Allocation System — Python port

Replaces legacy's CacheService request-ID guard. A repeat of the same
request_id within REQUEST_ID_TTL_SECONDS (900) must not write twice
(CLAUDE.md section 6, rule 12).

SQLite has no TTL of its own, so expired rows are pruned on write.

DIVERGENCE FROM LEGACY — what a duplicate returns.
Legacy stores only the marker '1' in the cache and answers a repeat with an
ERROR: response_(false, 'DUPLICATE_REQUEST', 'This save request was already
submitted. Reload the date to confirm the result.').

CLAUDE.md rule 12 instead says a repeat "returns the original result rather than
double-writing", and schema.sql gives `request_log` a `response_json` column for
exactly that. Two of the project's own documents describe replaying the result,
against one legacy behaviour that looks like a limitation of Apps Script's cache
rather than a decision. The documented behaviour is implemented here — a repeat
replays the stored response — and the divergence is flagged rather than hidden.
Say so if the legacy error response is wanted instead.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.idempotency import RequestLog
from rules.business_rules import REQUEST_ID_TTL_SECONDS

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _utc_now() -> datetime:
    """UTC, matching SQLite's datetime('now') which the column defaults to."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def find_live_entry(db: Session, request_id: str) -> RequestLog | None:
    """The stored record for this request_id, if it is still within the window.

    A row older than the TTL is treated as absent, so the same id becoming
    reusable after 900 seconds matches legacy's cache expiry.
    """
    row = db.get(RequestLog, request_id)
    if row is None:
        return None

    try:
        created = datetime.strptime(row.created_at, _TIMESTAMP_FORMAT)
    except (TypeError, ValueError):
        # An unparseable timestamp must not silently disable the guard.
        return row

    if _utc_now() - created > timedelta(seconds=REQUEST_ID_TTL_SECONDS):
        return None
    return row


def record(db: Session, request_id: str, user_email: str, endpoint: str, response_json: str) -> None:
    db.add(
        RequestLog(
            request_id=request_id,
            user_email=user_email,
            endpoint=endpoint,
            response_json=response_json,
            created_at=_utc_now().strftime(_TIMESTAMP_FORMAT),
        )
    )
    db.flush()


def release(db: Session, request_id: str) -> None:
    """Drop the guard so a corrected retry can reuse the id.

    Legacy does exactly this in its failure path (`cache.remove(cacheKey)`) —
    a failed save must not lock the operator out of retrying.
    """
    db.execute(delete(RequestLog).where(RequestLog.request_id == request_id))
    db.flush()


def prune_expired(db: Session) -> int:
    """Delete rows past the TTL. SQLite has no TTL, so this runs on write."""
    cutoff = (_utc_now() - timedelta(seconds=REQUEST_ID_TTL_SECONDS)).strftime(_TIMESTAMP_FORMAT)
    expired = list(db.scalars(select(RequestLog.request_id).where(RequestLog.created_at < cutoff)))
    if expired:
        db.execute(delete(RequestLog).where(RequestLog.request_id.in_(expired)))
        db.flush()
    return len(expired)
