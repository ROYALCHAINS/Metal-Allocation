"""
lock_repo.py — per-date serialization for saves and revisions.

Legacy: LockService.getScriptLock() with a 30s timeout (CONFIG.LOCK_TIMEOUT_MS).
Ported to a Postgres transaction-scoped advisory lock keyed by the allocation
date, per CLAUDE.md 6.11. The lock is released automatically at COMMIT or
ROLLBACK of the current transaction — callers must not span it across
sessions.
"""

from datetime import date as date_

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from rmas.services.exceptions import LockTimeoutError


def acquire_date_lock(db: Session, allocation_date: date_, timeout_seconds: float) -> None:
    timeout_ms = int(timeout_seconds * 1000)
    db.execute(text("SET LOCAL lock_timeout = :ms"), {"ms": f"{timeout_ms}ms"})
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": allocation_date.isoformat()})
    except OperationalError as exc:
        raise LockTimeoutError(
            "Another save is currently running. Wait a few seconds and try again.",
            code="LOCK_TIMEOUT",
        ) from exc
