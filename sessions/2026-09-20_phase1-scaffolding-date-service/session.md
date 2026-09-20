# Session: Phase 1 scaffolding + DateService port (Stage 2 kickoff)

Date: 2026-09-20

Goal: Begin Stage 2 (porting) now that `legacy files/` is verified complete and
byte-identical to what was reviewed. Implement everything that doesn't depend on the 10
open questions logged in `sessions/2026-09-19_rmas-legacy-review/session.md`, and stop at
anything that does rather than inventing an answer.

## What happened

Implemented and verified the unblocked slice of the Phase 1 plan:

**Backend scaffolding** (`rmas/`):
- `config.py` — `Settings` (pydantic-settings): `app_name`, `app_version`, `app_timezone`,
  `database_url` (placeholder default, override via `.env`).
- `database.py` — SQLAlchemy `engine`, `SessionLocal`, `Base`, `get_db()`. No models yet.
- `schemas/common.py` — `HealthResponse`.
- `main.py` — FastAPI app factory + `/health` endpoint. Run with `uvicorn main:app --reload`
  from inside `rmas/` (bare imports like `from config import settings` assume `rmas/` itself
  is the working root, matching `CLAUDE.md`'s documented commands, e.g. `pytest
  tests/test_allocation_service.py -v` with no `rmas/` prefix — no `rmas/__init__.py` was
  created, by design, so `rmas/` isn't itself a package).
- `rules/business_rules.py` — ported `Config.gs`'s `RULES` block plus `EPSILON`,
  `MAX_WEIGHT_KG`, `DECIMALS`, `LOCK_TIMEOUT_MS`, `REQUEST_ID_TTL_SECONDS`, verbatim. The
  three inert toggles (`allow_zero_previous_requirement`, `allow_zero_closing_balance`,
  `saved_date_immutable_for_users`) are kept as documentary constants only, per the
  reasoning already logged as open question #2 — no new guard-clause code was added around
  them.

**First business-logic port** (`services/date_service.py`, from `DateService.gs`):
- `to_date_key()` — parses `yyyy-MM-dd`, `dd/MM/yyyy`, `dd-MM-yyyy`, `dd-MMM-yyyy`, or
  passes through a `date`/`datetime`.
- `previous_source_date()` — the carry-forward rule: Monday → −2 days (Saturday), every
  other day → −1 day.
- `today_key()` — current date in `Asia/Kolkata` via `zoneinfo`.
- `format_display_date()` — `'Mon, 17-Aug-2026'` style, mirroring `formatDisplayDate_()`.
- Deliberately did **not** port `dateKeyToStorageDate_`/`STORAGE_HOUR` — `CLAUDE.md` §6 rule
  6 says a proper `DATE` column supersedes the noon-storage DST/UTC workaround.

**Root-level config files**: `requirements.txt` (pinned to what's already installed in
`.metal`: fastapi 0.141.1, SQLAlchemy 2.0.54, alembic 1.20.0, psycopg 3.3.6, pydantic
2.13.5/pydantic-settings 2.15.0, uvicorn 0.53.0, pytest 9.1.1, httpx 0.28.1),
`.env.example`, `.gitignore`.

**Tests** (`rmas/tests/`): `test_date_service.py` (carry-forward rule parametrized across
all 7 weekdays, plus all 4 date-string formats, passthrough, and rejection of an unknown
format), `test_health.py` (`TestClient` hits `/health`, asserts 200 + expected body). Ran
`pytest tests/ -v` from inside `rmas/` using the `.metal` venv directly — **15/15 passed**.

## Errors / issues encountered

None blocking. Two harmless `DeprecationWarning`s from `starlette.testclient`/`anyio`
internals (unrelated to this code, nothing to fix).

## Achievements

- Phase 1 backend scaffolding exists, runs, and is tested — not just proposed.
- First legacy file fully ported and verified: `DateService.gs` → `services/date_service.py`
  (Stage 2 for this one file; not yet retired per the three-stage lifecycle — Stage 3
  retirement of `legacy files/DateService.gs` should wait until this port has been reviewed,
  not happen automatically just because tests pass).
- Confirmed the intended run convention: commands in `CLAUDE.md`'s "Commands" section
  (`uvicorn main:app`, `pytest tests/...`) run with `rmas/` as the working directory, not
  the project root — settled by testing it, not just inferring it from the docs.

## Future things to implement / open questions

Deliberately stopped here because everything else in the porting order depends on at least
one of the 10 open questions from `sessions/2026-09-19_rmas-legacy-review/session.md`:

- `services/validation_service.py` (weight assertions, `computeTotals_`) is mostly unblocked
  and could go next — only touches open question #6 (the `'Any'` purity literal), which is
  data-layer, not validation-layer, so it may not even block this file. Good next candidate.
- `services/scope_service.py` (identity/admin-check, deny-list precedence, party scope) is
  blocked on open question #1 (auth mechanism — `google-auth` is installed but `CLAUDE.md`
  forbids Google API dependencies; no replacement decided).
- `models/`, `repository/`, `migrations/` are blocked on open questions #5 (scope table
  design), #6 (purity representation), and #8 (true sector count + real seed data).
- `staging_service.py`/`allocation_service.py` (the save/submit/revise orchestration) depend
  on both scope_service and the repository layer, so they wait on the above.
- Frontend scaffolding is blocked on open question #10 (one role-conditional Daily view vs.
  two literal views).

Recommend resolving open question #1 (auth mechanism) next — it's the one most other
unblocked work eventually funnels through.
