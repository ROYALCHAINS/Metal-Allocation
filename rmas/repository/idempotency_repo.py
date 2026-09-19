"""
idempotency_repo.py — request_id replay guard. See models/idempotency.py.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from rmas.models.idempotency import IdempotencyKey
from rmas.services.date_service import app_timezone


def is_active(db: Session, request_id: str, ttl_seconds: int) -> bool:
    """True when request_id was reserved within the last ttl_seconds."""
    row = db.scalar(select(IdempotencyKey).where(IdempotencyKey.request_id == request_id))
    if row is None:
        return False
    return (datetime.now(app_timezone()) - row.created_at) < timedelta(seconds=ttl_seconds)


def reserve(db: Session, request_id: str) -> None:
    """Legacy cache.put(cacheKey, '1', TTL)."""
    db.merge(IdempotencyKey(request_id=request_id, created_at=datetime.now(app_timezone())))
    db.flush()


def release(db: Session, request_id: str) -> None:
    """Legacy cache.remove(cacheKey) on failure, to allow a corrected retry."""
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.request_id == request_id))
    db.flush()
