"""
idempotency.py — replaces Apps Script's CacheService-based request_id guard
(Code.gs's `cache.put(cacheKey, '1', REQUEST_ID_TTL_SECONDS)`).

Not named in CLAUDE.md's original model list because the legacy system used
a runtime cache service with no DB equivalent; Postgres needs an explicit
table to get the same "repeat within 900s is rejected, a failed attempt can
retry immediately" behaviour (CLAUDE.md 6.12).
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from rmas.database import Base


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    request_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
