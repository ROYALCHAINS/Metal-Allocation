# Session: Login page + Dashboard shell (frontend)

Date: 2026-09-20

Goal: Build a login page and, after a successful Google OAuth login, show a Dashboard page.
Keep DB verification at SQLite-backed tests for now (explicit user decision — the live
Postgres server discovered last session is not being used yet).

## What happened

1. Before writing any HTML/CSS, read the legacy `Styles.html` and `Index.html` in full to
   find the real component class names rather than inventing new ones (CLAUDE.md section 7,
   "UI fidelity" — the visual design must be reproduced exactly). Found: `.app-header`/
   `.brand`/`.header-meta` (header), `.access-gate`/`.access-gate__icon/__title/__text`
   (the exact centered-card pattern legacy uses for restricted-access states), `.btn`/
   `.btn--primary`/`.btn--ghost`, `.role-pill`/`.role-pill--admin`/`.role-pill--user`
   (found in `Audit.html`, not `Scripts.html` — the role pill is actually set by the Audit
   module, not the Daily Allocation one).
2. Ported `legacy files/Styles.html`'s entire CSS body verbatim into
   `frontend/src/styles/tokens.css` — verified **byte-for-byte identical** to the legacy
   source from `:root {` onward via `diff`, not just visually similar.
3. Extracted the exact base64 brand logo from `legacy files/Index.html` programmatically
   (`grep -o`, not retyped) into `frontend/src/components/appHeader.js`, a new shared
   header component reused by both views — verified the embedded string matches the
   source exactly via a second `diff`.
4. Added `frontend/src/styles/app.css` — a small, clearly-commented set of new layout
   rules (centered card, welcome-card structure) for the login/dashboard shell, since
   neither page has a legacy equivalent (Apps Script had no login screen — identity was
   free from Google Workspace session binding). Built only from existing design tokens,
   doesn't touch or override any ported class.
5. Built the frontend:
   - `frontend/index.html` — shell, loads Google Fonts + `tokens.css` + `app.css`, mounts
     `<div id="app">`, loads `src/main.js` as an ES module.
   - `frontend/src/api/auth.js` — the only module that calls `fetch()` for auth
     (`getCurrentUser`, `loginUrl`, `logout`) — views never call fetch directly (CLAUDE.md
     section 3).
   - `frontend/src/views/login.js` — reuses `.access-gate`/`.btn--primary`, links to
     `/auth/login`.
   - `frontend/src/views/dashboard.js` — reuses the header with user identity + role pill,
     a welcome card, and a **placeholder note** that KPIs/charts arrive once
     `ReportService.gs` is ported — deliberately not fabricating dashboard data that the
     backend can't yet produce (CLAUDE.md section 6, rule 23: never invent behaviour).
   - `frontend/src/main.js` — calls `GET /auth/me`; renders dashboard on success, login on
     401.
6. Wired the frontend into the backend: `rmas/main.py` now mounts
   `StaticFiles(directory=frontend, html=True)` at `/`, registered **after** `/health` and
   the `/auth/*` router so those routes still take precedence. Same-origin serving means no
   CORS handling is needed for the session cookie.
7. Verified everything actually runs, not just compiles:
   - `pytest tests/ -v` — still 25/25 passing after the static-file mount.
   - Started the real dev server (`uvicorn main:app`) and hit `/`, `/src/main.js`,
     `/src/styles/tokens.css`, `/auth/me`, `/health` directly with `curl` — all correct
     status codes.
   - Loaded the app in an actual browser (Claude in Chrome): the login page rendered
     correctly (real logo, header, "Sign in to continue" card, working link).
   - Clicking "Sign in with Google" genuinely reached Google's real OAuth endpoint, which
     correctly rejected it with "Missing required parameter: client_id" — end-to-end proof
     the redirect URL construction is correct, given no real credentials are configured yet.
   - Rendered `dashboard.js` directly via a dynamic `import()` in the browser console with
     a fake admin user (no real Postgres/session available to complete a live OAuth
     round-trip) — header showed the user's name and an "ADMIN" role pill correctly styled;
     clicking "Sign out" correctly called `/auth/logout` and returned to the login view.
   - Stopped the dev server and closed the browser tab afterward.

## Errors / issues encountered

- Chrome's `screenshot` action twice appeared to coincide with an unintended navigation to
  Google's real OAuth error page (not something I explicitly clicked) — possibly a stray
  cursor-position artifact from the automation tooling. Not harmful (no data was sent
  anywhere sensitive, and it happened to confirm the redirect endpoint works), but worth
  being aware of: re-navigated back to `http://127.0.0.1:8123/` and confirmed via
  `location.href` in a `javascript_tool` call before proceeding, rather than trusting the
  screenshot alone.
- Could not complete a real end-to-end OAuth login in the browser (no Google Client ID/
  Secret configured yet, per the still-open item from the previous session) — worked around
  it by rendering `dashboard.js` directly against a fake user object to verify the view
  itself, which is a real gap: the full login → callback → dashboard round trip is only
  verified via the mocked pytest suite, not a live browser session.

## Achievements

- A visually faithful login page and dashboard shell exist and are wired to the real
  `/auth/*` backend from the previous session — not just static mockups.
- `tokens.css` and the header logo are proven byte-identical to the legacy visual contract,
  not eyeballed.
- Confirmed in a real browser, not just tests: the login page renders correctly, the OAuth
  redirect reaches Google with a correctly-constructed URL, the dashboard renders the
  correct user/role, and sign-out correctly returns to login.

## Future things to implement / open questions

- **A real Google OAuth Client ID/Secret is still needed** to complete an actual live login
  round-trip in the browser (currently only verified via mocked tests + a faked dashboard
  render). This was already flagged last session — still outstanding.
- The dashboard is a placeholder. Real KPIs/charts require porting `ReportService.gs` →
  `services/report_service.py` first (still blocked on open questions #5/#6/#8 from the
  2026-09-19 review — scope tables, purity representation, true sector count/seed data).
- No nav tabs were added yet (Daily Allocation / Reports / Audit) since only the dashboard
  view exists so far — CLAUDE.md's open question #10 (one role-conditional Daily view vs.
  two literal views) is still unresolved and will matter once those views are built.
- Postgres verification is still deliberately deferred, per this session's explicit
  instruction — SQLite-backed tests remain the verification method for now.
