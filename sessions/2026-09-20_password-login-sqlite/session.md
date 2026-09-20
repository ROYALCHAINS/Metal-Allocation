# Session: Replace Google OAuth with password login; switch to SQLite

Date: 2026-09-20

Goal (explicit, three-part instruction): (1) remove the Google OAuth implementation and
build normal username/password sign-in instead; (2) closed roster — no signup page, login
only works if the email/password already exist in the backend database; (3) update
`CLAUDE.md` for the database, switching from PostgreSQL to SQLite for now, and actually
create the database/tables/schema, not just plan them.

Also addressed a process concern raised at the start of this session: the previous
session's browser automation drove the user's real, logged-in Chrome browser (Claude in
Chrome controls the actual browser, not a sandbox), which the user did not want. Going
forward, browser automation on this project only happens if explicitly requested — the
user will run and test the server themselves.

## What happened

1. **Updated `CLAUDE.md`** before touching code:
   - Section 4: `PostgreSQL` → `SQLite` as the current database, with a note that moving
     back is expected to be a `DATABASE_URL` change, not a rewrite. Reverted the Google API
     carve-out to a flat "no Google dependency of any kind," with history noted.
   - Section 6 rule 11: replaced the OAuth decision with the username/password decision
     (bcrypt hashing, closed roster, no signup page, accounts provisioned via
     `create_user.py`), explicitly noting it supersedes the OAuth decision made and removed
     the same day.
   - Critical Rules item 1: added a SQLite-specific caveat — SQLite has no native
     fixed-point decimal storage, so `Numeric(asdecimal=True)` (string-based binding, not
     float) is what prevents float drift, and this must be proven with an explicit
     round-trip test before any weight-bearing table is trusted, not assumed.
2. **Removed the OAuth implementation and built password auth**:
   - `models/user.py` — added `password_hash` (bcrypt hash, never plaintext).
   - `services/password_service.py` (new) — `hash_password`/`verify_password`, bcrypt only.
   - `routers/auth.py` — rewritten: `POST /auth/login` (email+password →
     `CurrentUserResponse` or 401), `POST /auth/logout`, `GET /auth/me`. Removed the
     `GET /auth/login` redirect, `GET /auth/callback`, and the httpx/google-auth adapter
     classes entirely.
   - `schemas/auth.py` — added `LoginRequest`.
   - `create_user.py` (new, project root of `rmas/`) — the only way an account gets
     created, since there's no signup page. Prompts for the password via `getpass` (never
     a CLI argument, never echoed) so it never passes through me or shell history.
3. **Switched the database to SQLite**:
   - `config.py` — `database_url` now defaults to an absolute-path SQLite file at
     `rmas/rmas.db` (resolved via `Path(__file__)`, not the process's cwd, so it's correct
     whether launched as `python main.py` from anywhere or `uvicorn main:app` from inside
     `rmas/`). Removed the Google OAuth settings entirely.
   - `database.py` — added `check_same_thread: False` for SQLite (FastAPI runs sync routes
     across threads).
   - `migrations/env.py` — added SQLite batch-mode rendering (`render_as_batch`), needed
     because SQLite can't `ALTER`/`DROP COLUMN` directly — Alembic recreates the table
     instead. No effect on other dialects.
   - `migrations/versions/0001_create_users_table.py` — added `password_hash` column
     (edited in place rather than adding 0002, since nothing had been applied anywhere yet).
   - `requirements.txt` — removed `psycopg[binary]` and `google-auth`, added `bcrypt==5.0.0`
     (installed and confirmed matching).
   - `.env`/`.env.example` — removed all Google settings; `DATABASE_URL` left unset/
     commented so the SQLite default applies.
   - `.gitignore` — added `*.db`/`*.db-journal`.
4. **Also fixed while touching `python main.py` support** (raised by the user's earlier
   "me as an end user will run the py file" framing): added a real
   `if __name__ == "__main__":` block to `main.py` so `python main.py` actually starts a
   server (it previously just defined the app object and exited).
5. **Rewrote `tests/test_auth_flow.py`** entirely for password login (the old file mocked
   Google's endpoints, which no longer exist): correct login sets a session; wrong password
   rejected; unknown email rejected; unknown-email and wrong-password give the *identical*
   error (never leak which one it was); `/me` requires auth; logout clears the session; a
   denied user can still log in (the deny flag only blocks admin status, not login itself —
   matching legacy, where `NON_ADMIN_EMAILS` only ever affected `isAdministrator_()`, never
   gated login).
6. **Actually created the database and schema** (not just planned it): ran
   `alembic upgrade head` against the real `rmas/rmas.db` — confirmed via direct `sqlite3`
   inspection that the `users` table exists with exactly the expected columns (`id`,
   `email`, `display_name`, `role`, `password_hash`, `is_denied`) plus Alembic's own
   `alembic_version` tracking table.
7. **Verified everything actually runs**, not just imports cleanly:
   - `pytest tests/ -v` — 26/26 passing (7 in the rewritten auth-flow file).
   - Started the real dev server against the real SQLite file (not a test stand-in) and hit
     `/health`, `/`, `/auth/me`, `/auth/login` with `curl` — all correct status codes,
     confirmed via the server's own request log, not just curl's exit code.
   - Confirmed `create_user.py --help` parses correctly. Deliberately did **not** run it to
     create a real account — that would require me to see or choose the user's password,
     which is exactly the kind of credential-handling this design is meant to avoid. Left
     account creation for the user to do themselves.
   - Grepped the entire `rmas/` and `frontend/` trees for any remaining
     `google`/`oauth` reference: only Google Fonts links (unrelated, legacy already used
     them) and intentional historical docstring notes remain.
   - Stopped the dev server afterward (`taskkill` by PID, found via `netstat`).
8. **Did not use browser automation this session**, per the user's stated preference —
   all verification was via `pytest`, `curl`, and direct `sqlite3` inspection.

## Errors / issues encountered

- None blocking. The only thing worth flagging: `sqlite:///./rmas.db` (a relative path) was
  my first instinct for the SQLite URL, but that resolves relative to the process's working
  directory — the same class of bug just fixed for `.env` loading last session. Caught it
  before running anything, and used `Path(__file__).resolve().parent / 'rmas.db'` instead so
  the database file is found correctly regardless of where `python main.py` is launched
  from.

## Achievements

- The login flow is now password-based end to end, verified against a real SQLite
  database file with a real Alembic-applied schema — not just against test stand-ins.
- No Google dependency of any kind remains in the codebase (confirmed by grep).
- `CLAUDE.md` reflects both pivots as dated decisions with reasoning, not just the code.

## Follow-up (same day, after this entry was first written)

The user ran `create_user.py` themselves (`shubham.g@royalchains.com`, role `admin`) and
then `python main.py`, and confirmed logging in successfully through their own browser at
`localhost:8000`. This is the first genuine end-to-end confirmation of the full login flow
by the actual end user, not just automated tests — the password-login + SQLite pivot is
fully working in practice, not just in theory.

## Future things to implement / open questions

- ~~No real user account exists yet.~~ Done — `shubham.g@royalchains.com` (admin) now
  exists in `rmas/rmas.db` and has successfully logged in.
- The SQLite-vs-PostgreSQL numeric-precision caveat now recorded in `CLAUDE.md` (Critical
  Rules item 1) has no test yet, because no weight-bearing table exists yet — it must be
  added before (not after) `allocations`/`flows` tables are created, per the rule.
- All open questions from `sessions/2026-09-19_rmas-legacy-review/session.md` that don't
  concern auth are still outstanding (scope tables, purity representation, true sector
  count/seed data, one Daily view vs. two).
- Next unblocked candidate per the migration order is still `services/validation_service.py`.
