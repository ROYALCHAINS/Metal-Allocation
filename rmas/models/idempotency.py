"""
models/idempotency.py
Royal Metal Allocation System — Python port

Replaces legacy's CacheService request-ID guard. A repeat of the same
request_id within REQUEST_ID_TTL_SECONDS (900) returns the stored response
rather than double-writing (CLAUDE.md section 6, rule 12). Prune rows older
than the TTL on write — SQLite has no TTL of its own.
"""

from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class RequestLog(Base):
    __tablename__ = "request_log"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_email: Mapped[str] = mapped_column(String, nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    response_json: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("(datetime('now'))"), index=True
    )
