"""
config.py
Royal Metal Allocation System — Python port

Single source of deployment configuration (env-backed). Business rule toggles
live in rules/business_rules.py, not here — this file only holds settings
that differ per environment (DB, timezone, auth). No secrets are hard-coded.

Ports: Config.gs's SPREADSHEET_ID / TIMEZONE_FALLBACK / LOCK_TIMEOUT_MS /
REQUEST_ID_TTL_SECONDS / APP_NAME / APP_VERSION.
"""

from functools import lru_cache
from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Royal Metal Allocation System"
    app_version: str = "1.0.0-py"  # legacy Apps Script build was '5H'; this is the new lineage

    database_url: str = "postgresql+psycopg://rmas:rmas@localhost:5432/rmas"

    # Legacy TIMEZONE_FALLBACK. The application is single-timezone; every date
    # key is produced and compared in this zone.
    app_timezone: str = "Asia/Kolkata"

    # Google OAuth / Workspace SSO. The frontend obtains a Google ID token;
    # the backend verifies its signature and audience against this client id.
    google_oauth_client_id: str = ""
    # Restrict accepted identities to a Workspace domain, e.g. "royalchains.com".
    # Blank means any verified Google identity is accepted (role/scope lookup
    # in the database still decides what they can do).
    google_workspace_hosted_domain: str = ""

    # Legacy LOCK_TIMEOUT_MS (30000) — Postgres advisory lock wait, in seconds.
    save_lock_timeout_seconds: float = 30.0

    # Legacy REQUEST_ID_TTL_SECONDS — idempotency window for request_id replay.
    request_id_ttl_seconds: int = 900

    # Legacy DECIMALS / EPSILON / MAX_WEIGHT_KG. Kept here (not in
    # business_rules.py) because they are numeric-precision constants, not
    # business policy toggles — see rules/business_rules.py docstring.
    weight_decimals: int = 3
    weight_epsilon: Decimal = Decimal("0.0005")
    max_weight_kg: Decimal = Decimal("100000")


@lru_cache
def get_settings() -> Settings:
    return Settings()
