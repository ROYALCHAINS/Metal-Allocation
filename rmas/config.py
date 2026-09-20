"""
config.py
Royal Metal Allocation System — Python port

Typed application settings, loaded from environment variables / .env.
Ports the non-rule parts of Config.gs (app name/version, timezone). Business
rule toggles live in rules/business_rules.py, not here (CLAUDE.md section 2,
"Where things belong").
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved relative to this file, not the process's working directory, so
# both are found whether the app is launched as `python main.py`,
# `uvicorn main:app` from inside rmas/, or from the project root.
_RMAS_DIR = Path(__file__).resolve().parent
_ENV_FILE = _RMAS_DIR / ".env"
_DEFAULT_SQLITE_URL = f"sqlite:///{(_RMAS_DIR / 'rmas.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_name: str = "Royal Metal Allocation System"
    app_version: str = "5H"
    app_timezone: str = "Asia/Kolkata"

    # SQLite for now (CLAUDE.md section 4, resolved 2026-09-20) — file lives
    # at rmas/rmas.db, gitignored. Override via .env to point elsewhere; a
    # move back to PostgreSQL is meant to be just a DATABASE_URL change.
    database_url: str = _DEFAULT_SQLITE_URL

    # Signs the session cookie (itsdangerous, via Starlette's SessionMiddleware).
    # The cookie carries only a signed user id — role/scope are still resolved
    # server-side from the `users` table on every request (rule 8). This
    # default is INSECURE and only for local dev — a real deployment must set
    # SESSION_SECRET_KEY to a long random value via .env.
    session_secret_key: str = "dev-insecure-change-me"


settings = Settings()
