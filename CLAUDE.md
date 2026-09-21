# CLAUDE.md — Royal Metal Allocation System (RMAS)

Guidance for Claude Code when working in this repository.

---

## 1. Project Overview

RMAS tracks the daily allocation of precious metal across manufacturing sectors for
Royal Chains. It answers one question per working day: given the metal acquired and
the requirement raised by each party, how much is allotted to each sector, and what
balance carries forward?

The system is being **ported from Google Apps Script + Google Sheets to Python +
JavaScript**. The Apps Script implementation (version `5H`) is the behavioural
reference. Where this document and the legacy `.gs` source disagree, **the legacy
source wins** — raise the conflict rather than guessing.

### Core domain model

Each row of allocation is a `(date, party, sector)` triple carrying:

```
balance = previous_requirement + today_required - alloted
```

- **Requirement** is demand. **Acquired** is supply. Demand may legitimately exceed
  supply; the shortfall carries forward as `balance`.
- A zero closing balance is valid and expected.
- All weights are in **kilograms to exactly 3 decimals** (gram precision).

### Two-stage daily workflow

1. **Operators submit** — each operator is scoped to one or more parties. They enter
   `today_required` per allocation sector and `today_acquired` per flow sector. These
   land in a **staging** table, not the master tables.
2. **Administrator saves** — an admin reviews staged values, sets `alloted` per
   sector, and commits. Only this step writes to the allocation and flow masters, and
   only this step computes `balance`.
3. **Revision** — an admin may revise an already-saved date. This requires a written
   reason and produces an audit entry containing both the previous and updated state.

Every write is audited. The audit trail is append-only.

### Roles

- **Administrator** — commits allocations, revises saved dates, reads the audit log.
- **Operator** — submits requirements for their assigned parties only, and sees only
  their own party's data in reports and the dashboard.

Authorisation is resolved **server-side on every request** from the authenticated
identity. The browser is never trusted with role or scope. An explicit deny entry
always overrides an admin grant.

---

## 2. Architecture

```
rmas/
├── main.py                  # FastAPI app factory, middleware, router registration
├── config.py                # Settings (pydantic-settings). No secrets in code.
├── database.py              # Engine, SessionLocal, Base, get_db dependency
│
├── routers/                 # HTTP layer ONLY
│   ├── allocations.py
│   ├── staging.py
│   ├── flow.py
│   ├── reports.py
│   ├── audit.py
│   └── auth.py
│
├── services/                # ALL business logic and rule enforcement
│   ├── allocation_service.py
│   ├── staging_service.py
│   ├── validation_service.py
│   ├── audit_service.py
│   ├── report_service.py
│   ├── date_service.py
│   └── scope_service.py
│
├── repository/              # Persistence. The only place SQLAlchemy is touched.
│   ├── allocation_repo.py
│   ├── staging_repo.py
│   ├── flow_repo.py
│   ├── audit_repo.py
│   └── sector_repo.py
│
├── schemas/                 # Pydantic request/response models
├── models/                  # SQLAlchemy ORM models
├── rules/
│   └── business_rules.py    # Rule toggles — single source of truth
├── migrations/              # Alembic
└── tests/

frontend/
├── src/
│   ├── api/                 # fetch wrappers, one module per router
│   ├── views/               # allocation, staging, reports, dashboard, audit
│   ├── components/          # reusable UI (tables, charts, date picker)
│   ├── lib/                 # formatting, rounding, date helpers
│   └── styles/
└── index.html
```

### Where things belong

| Concern | Location | Never in |
|---|---|---|
| Route definitions, HTTP status, dependency injection | `routers/` | `services/`, `repository/` |
| Business rules, calculations, workflow orchestration | `services/` | `routers/`, `repository/` |
| SQLAlchemy queries, transactions, session use | `repository/` | `routers/`, `services/` |
| Request/response shapes, field validation | `schemas/` | `models/` |
| Table definitions, relationships, constraints | `models/` | `schemas/` |
| Rule toggles and thresholds | `rules/business_rules.py` | anywhere else |

**Layering rule:** `routers → services → repository → models`. Never skip a layer,
never call upward. A router that imports a SQLAlchemy model is a bug. A service that
opens a `Session` is a bug.

### Legacy file mapping

| Apps Script file | Ports to |
|---|---|
| `Config.gs` | `config.py` + `rules/business_rules.py` |
| `Code.gs` | `routers/allocations.py` + `services/allocation_service.py` |
| `DataService.gs` | `repository/` |
| `SchemaService.gs` | Dropped — replaced by explicit schema (see Critical Rules) |
| `StagingService.gs` | `services/staging_service.py` + `services/scope_service.py` |
| `ValidationService.gs` | `services/validation_service.py` |
| `ReportService.gs` | `services/report_service.py` |
| `AuditService.gs` | `services/audit_service.py` |
| `DateService.gs` | `services/date_service.py` |
| `Index/Reports/Audit.html`, `Scripts.html` | `frontend/src/` |

---

## 3. Code Style

### Python

- **Type hints everywhere** — parameters, return types, and class attributes. No bare
  `dict` or `list`; use `dict[str, Decimal]`, `list[AllocationRow]`.
- **Pydantic models for every request and response.** No raw dicts crossing an API
  boundary.
- **Keep functions small and focused.** One function, one responsibility. If it needs
  a section comment to explain its second half, split it.
- Private helpers are prefixed with `_`, mirroring the legacy `_` suffix convention.
- Service functions raise domain exceptions (`ValidationError`, `ScopeError`,
  `DuplicateRequestError`). Routers translate those to HTTP responses. Services never
  import `HTTPException`.
- Docstrings state *why*, not *what*. The signature already says what.
- `snake_case` for functions and variables, `PascalCase` for classes,
  `UPPER_SNAKE` for constants.

### Naming

Keep domain vocabulary identical to the legacy system so the two can be compared
during the port: `previous_requirement`, `today_required`, `alloted`, `balance`,
`acquired`, `party`, `sector`, `purity`, `priority`.

Note the legacy spelling **`alloted`** (one `l`). Keep it. Renaming it to `allotted`
breaks every comparison against historical data.

### JavaScript

- ES modules. No global namespace pollution.
- `const` by default, `let` when reassigned, never `var`.
- Keep API calls in `src/api/`. Views call the API layer, never `fetch` directly.
- All money/weight formatting goes through one helper in `src/lib/`. Do not scatter
  `toFixed()` calls through views.
- No framework is assumed — do not introduce React/Vue without asking.

---

## 4. Preferred Libraries and Tech Constraints

**Use:**

- **FastAPI** — API framework
- **Pydantic v2** — validation and serialisation
- **SQLAlchemy 2.x** — ORM, with the modern `select()` style
- **Alembic** — migrations
- **SQLite** — current database, resolved 2026-09-20. PostgreSQL was the original target
  (see section 6, "Database" for why this changed and what it means for numeric
  precision) — moving back to PostgreSQL later is expected to be a `DATABASE_URL` change,
  not a rewrite, since nothing above the repository layer should know which database is
  in use.
- **pytest** + **httpx** — testing
- **Decimal** (`decimal.Decimal`) — every weight, everywhere

**Do not introduce new dependencies unless necessary.** If a new package is genuinely
required, say why and what it replaces before adding it.

**Explicitly avoid:**

- `float` for any weight, requirement, allotment or balance — see Critical Rules
- Pandas for request-path logic (acceptable in offline migration scripts only)
- ORM-level lazy loading in report queries; be explicit
- Raw SQL outside `repository/`
- Any Google API dependency, including for login — the port exists to remove Google as a
  dependency entirely. (Google OAuth login was tried and then explicitly replaced with
  username/password on 2026-09-20 — see section 6, "Identity, scope and authorisation".)

---

## 5. Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server
uvicorn main:app --reload

# Run tests
pytest

# Single test file
pytest tests/test_allocation_service.py -v

# Coverage
pytest --cov=rmas --cov-report=term-missing

# Migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1

# Lint and format
ruff check .
ruff format .
mypy rmas/

# Frontend
cd frontend && npm install
npm run dev
npm run build
```

---

## 6. Critical Rules

### Numeric precision

1. **Never use `float` for weights.** `Decimal` in Python, **`INTEGER` grams in the
   database** — resolved 2026-09-20, see `schema.sql`'s design note. This system
   reconciles physical gold; float drift is a real financial error, not a rounding
   cosmetic.
   - **Weights are stored as an integer number of grams**, with a `_g` column suffix so
     the unit cannot be mistaken (`alloted_g`, `balance_g`, `acquired_g`, `value_g`).
     Legacy worked in kilograms to exactly 3 decimals, and 3 decimals of a kilogram is
     precisely 1 gram, so this is lossless *by construction* — it does not depend on
     driver behaviour the way a `NUMERIC`-typed column on SQLite would, since SQLite has
     no exact decimal type and `REAL` is binary floating point.
   - **All conversion goes through `services/weight_service.py`** — `kg_to_grams()` /
     `grams_to_kg()` — and nowhere else. That module refuses a `float` argument outright
     rather than silently converting it. Proven by `tests/test_weight_service.py`
     (exact round-trips, accumulation without drift, `ROUND_HALF_UP` at the third
     decimal, float rejection).
   - The `v_allocation_kg` / `v_flow_kg` views expose kilograms **for presentation only**.
     Never compute on them.
2. **Round to exactly 3 decimals** at every persistence boundary, using
   `ROUND_HALF_UP`. The legacy epsilon for comparisons is `0.0005` — half of the third
   decimal place. Use it for equality checks; never compare weights with `==`.
3. `MAX_WEIGHT_KG = 100000` is a sanity ceiling on any single numeric input. Keep it.

### Business rule toggles — do not flip

The following toggles are **deliberately disabled** in the legacy system. Port them as
`False` and **do not re-enable them**, even if a validation gap looks like a bug:

| Toggle | State | Meaning |
|---|---|---|
| `REQUIRE_FULL_ALLOCATION` | `False` | Alloted need not equal acquired |
| `REQUIRE_POSITIVE_ALLOTED` | `False` | Zero allotment is permitted |
| `BLOCK_OVER_ALLOCATION` | `False` | Alloted may exceed acquired |
| `OPERATOR_REQUIRED_WITHIN_ACQUIRED` | `False` | Requirement is not capped by supply |

These were switched off by business decision. There is an **unresolved conflict**
between the code state and an earlier "final business decisions" document that says
`REQUIRE_FULL_ALLOCATION` and `REQUIRE_POSITIVE_ALLOTED` should be enforced. That
conflict has never been settled. Do not resolve it in either direction without an
explicit instruction.

Currently enabled and to be preserved: `ALLOW_ZERO_PREVIOUS_REQUIREMENT`,
`ALLOW_ZERO_CLOSING_BALANCE`, `REQUIRE_POSITIVE_ACQUIRED`,
`CARRY_FORWARD_FROM_LATEST_SAVED`, `ALLOW_ADMIN_REVISION`, `REQUIRE_REVISION_REASON`
(minimum 10 characters), `SAVED_DATE_IMMUTABLE_FOR_USERS`.

### Dates

4. **Carry-forward source date rule:** Monday looks back to **Saturday** (−2 days);
   every other day looks back 1 day. This encodes the six-day working week — do not
   "simplify" it to yesterday.
5. When `CARRY_FORWARD_FROM_LATEST_SAVED` is on and nothing was saved on the rule
   date, fall back to the most recent saved date. Skipped days must never silently
   reset a balance to zero.
6. Store dates as **date**, not timestamp. The legacy system stored at **12:00 local**
   specifically to survive DST and UTC rollover; a proper `DATE` column supersedes that
   hack, but never reintroduce a timezone-naive datetime.
7. Application timezone is **Asia/Kolkata**.

### Identity, scope and authorisation

8. **Scope is enforced server-side on every request, without exception.** Operators see
   only their assigned parties. Never accept a party or sector filter from the client
   as authoritative — intersect it with the server-resolved scope.
9. An entry in the deny list **always** overrides an admin grant.
10. Never return the administrator list, or any other account's scope, to the client.
11. **Authentication is username/password — resolved 2026-09-20, replacing an earlier
    Google OAuth decision made the same day.** Legacy identity came free from
    `Session.getActiveUser()` under Google Workspace; the new stack has no equivalent.
    Google OAuth was implemented first, then explicitly removed in favor of a plain
    email/password login, per instruction — no Google dependency of any kind remains
    (section 4). Passwords are hashed (`bcrypt`), never stored or logged in plaintext, and
    never compared with anything but a constant-time verify function.
    - **Closed roster, no self-service signup, no signup page.** A user must already
      exist in the `users` table — with a password hash already set — for login to
      succeed. There is exactly one page: login. Accounts are provisioned out-of-band via
      `create_user.py`, run by an administrator directly against the database, mirroring
      legacy's model of hand-editing `Config.gs`'s `ADMIN_EMAILS`/`OPERATOR_PARTIES`.
    - Role/party scope/deny status are still always resolved server-side from the `users`
      table on every request (rule 8) — a successful password check proves *who*, never
      *what they may do*.

### Concurrency and idempotency

11. Saves and revisions must be **transactional and serialised per date**. The legacy
    system used a 30-second script lock; use `SELECT ... FOR UPDATE` or an advisory
    lock on the allocation date.
12. **Preserve request-ID idempotency.** Clients send a `request_id`; a repeat within
    the 900-second window returns the original result rather than double-writing. This
    guards against double-clicks and retries.

### Audit

13. The audit log is **append-only**. No updates, no deletes, no exceptions.
14. Every audit entry records both **previous and updated** state for allocation and
    flow, plus the actor, timestamp, action type, revision number, reason, request ID
    and status. Failed attempts are logged too, not just successes.

### Schema and data

15. **Sector definitions are data, not code.** Sector names, priorities and purities
    live in the database, seeded from the Metal Generator sheet. **Never hard-code a
    sector name, party name, or purity value anywhere in the codebase.**
16. The legacy system detected spreadsheet columns by **header label** because column
    order drifted. In SQL this problem disappears — use an explicit schema and drop the
    label-matching logic. This is the one legacy behaviour that is intentionally *not*
    ported.
17. Staging rows carry a record type of `ALLOCATION` or `FLOW`. Keep the two separate;
    they are different sets with different counts and no shared names. **The Metal Flow
    table is keyed by PARTY, not by order type** — its 8 rows are the parties metal
    arrives for (legacy range `I7:I14`, `EXPECTED.FLOW_ROWS: 8`), each mapping to itself
    as its own party. **The UI labels that column "Party" on every screen.** One party
    supplies many allocation sectors; that one-to-many link through `party` is the only
    join between demand and supply, and there is no sector-to-sector mapping anywhere.
    See `SECTORS_EXPLAINED.md`.
17a. **`schema.sql` + `DATABASE_OVERVIEW.md` are the schema reference** (supplied
    2026-09-20). The SQLAlchemy models in `models/` and the Alembic migration `0002`
    implement it. Three deliberate departures, each documented in the relevant model's
    docstring rather than applied silently:
    - `app_user.password_hash` — **added**. `schema.sql` predates the username/password
      decision (rule 11) and has no password column, so login could not work without it.
    - `metal_allocation_audit_log.action_type` — **widened** from six values to the nine
      legacy actually writes. `schema.sql` lists only `AuditService.gs`'s `AUDIT_ACTIONS`
      and omits `SUBMIT_REQUIREMENT`/`BLOCKED_RESUBMISSION`/`FAILED_SUBMISSION`, which
      `StagingService.gs`'s `stagingAuditAction_()` emits to the same log. Left as-is,
      every operator-submission audit write would be rejected by the CHECK once staging
      is ported.
    - `metal_allocation_audit_log.allocation_date` — **made NULLABLE** (migration
      `0004`, 2026-09-20), with the format CHECK relaxed to `allocation_date IS NULL
      OR <format test>` so a NULL is allowed while a malformed date is still refused.
      `PROMPT_audit_log.md` rule 4 requires that an entry with no allocation date — a
      hard failure recorded before the date could be resolved — is never excluded by
      the date window. With `schema.sql`'s NOT NULL, no such row could be written at
      all, so the rule was unreachable and the log could not record the very failures
      it exists for. The date filter in `audit_repo` spares undated rows.
    - `metal_allocation_audit_log.parent_audit_id` — **added**, and `action_type`
      **widened again** to admit `RECALCULATE` (migration `0005`, 2026-09-22).
      `schema.sql` predates the forward cascade, which writes one audit entry per
      later date it recomputes, each linked to the `REVISE` entry that caused it.
      Deliberately not a foreign key, matching `request_id`: nothing turns on
      `PRAGMA foreign_keys`, so a self-FK would be declarative only — and would
      quietly start being enforced the day somebody enabled it, on a table whose
      triggers forbid deleting anything. `RECALCULATE` is a separate value from
      `REVISE` on purpose: the Revisions KPI counts administrator edits, and a
      cascade is a consequence of one, not another edit.
    - `metal_requirement_staging.status` — **changed** from `'PENDING'` to legacy's
      `STAGING_STATUS` vocabulary (`SUBMITTED`/`CONSUMED`, now CHECK-constrained).
      `markStagingConsumed_()` only ever matches `SUBMITTED` rows, so `PENDING` rows
      would be silently skipped at commit time.
    - **`flow_sector` holds the legacy 8 party names** (Royal Chain, Aalishaan, Aqua,
      ARK, IHG, Titan, Malabar, Aditya Birla), each its own party — so
      `DATABASE_OVERVIEW.md`, `schema.sql` and `EXPECTED.FLOW_ROWS: 8` describe this
      table correctly and this is **not** a departure. Recorded here only because it
      round-tripped: between 2026-09-20 and 2026-09-21 it briefly held the 21 allocation
      sector names instead, and that was reversed. The allocation list is untouched at
      21. **Known consequence:** `Factory` owns 8 allocation sectors but is not one of
      the 8 flow parties, so it has demand with no supply row, while the six brand
      parties have supply with no demand. Both are reported by
      `python seed_reference_data.py --report`; `Factory` is confirmed correct and its
      sectors are not to be re-parented onto the brand parties.
    - `sector.priority` and `metal_master.priority_snapshot` — **`TEXT`, not `INTEGER`**
      (migration `0003`). The sheet writes `Priority 1`…`Priority 6` and legacy keeps it
      a string that users see unchanged: `ReportService.gs` uses it as the report
      filter-dropdown label (line 204), as the "by priority" dashboard grouping key
      (line 587), and in text search (line 107). It is stored verbatim — never parsed,
      renumbered or reformatted. The `.badge--p1`…`.badge--p6` class is derived from the
      label client-side by matching the first digit, exactly as legacy's
      `priorityClass()` does.

### Known legacy inconsistencies

Carry these forward as *questions*, not as ported behaviour:

- ~~`RANGES.ALLOCATION_SECTORS` is `A7:C25` (**19 rows**) while
  `EXPECTED.ALLOCATION_ROWS` is **21**.~~ **RESOLVED 2026-09-20: the answer is 21.** The
  supplied sheet data (`seed/sector names.csv`) contains exactly 21 allocation sectors, so
  `EXPECTED.ALLOCATION_ROWS` was right and the `A7:C25` range comment — and `Index.html`'s
  static "19 sectors" chip — are both stale. Priorities run 1-6, matching `Styles.html`'s
  `.badge--p1`…`.badge--p6`. Do not reintroduce a 19 anywhere.
- `Config.gs` declares `buildTag_Config_()` **twice**, returning `'5C'` and then
  `'5H'`. The second declaration wins. The version check is therefore weaker than it
  appears.
- The dashboard's "Closing Balance Trend" chart is labelled *"cumulative physical vault
  stock position"* but actually plots the summed outstanding `balance`. The label is
  wrong, not the data. Decide the intended metric before porting the dashboard.

### Working practice

18. **Read before writing.** Consult the relevant legacy `.gs` file before changing
    ported behaviour. Do not infer rules from this document alone.
19. **Minimum files touched.** Solve the problem in the fewest files that can correctly
    hold the change.
20. **Do not modify `database.py` or `migrations/` unless the task requires it.**
21. **Preserve existing architecture and business logic** unless a change is explicitly
    requested.
22. For UI and design work, **propose the structure before altering production code.**
23. Never invent a sector name, party name, field, business rule, or system behaviour.
    If the information is not in the source or this document, ask.

---

## 7. Legacy Reference

The Apps Script implementation being ported from is documented in
`docs/FILE_SUMMARIES.md` — a per-file map of all 20 `.gs` and `.html` files
(~10,280 lines), covering what each file owns and which functions live where.

Consult it before changing any ported behaviour, to find which legacy file owns the
logic in question. **It is a locator, not a specification.** The legacy source is
authoritative; where the summary and the source disagree, the source wins and the
conflict should be raised rather than resolved silently.

The open questions under *Known legacy inconsistencies* in section 6 are the canonical
record of unresolved issues. Do not duplicate that list elsewhere.

### Legacy source location and lifecycle

The 20 `.gs`/`.html` files live in `legacy files/` at the project root (see that folder's
`README.md`) — reference material only; nothing in the new application reads or runs them.
They move through three stages:

1. **Reference** — present in `legacy files/`, read before porting any behaviour they own.
2. **Coexistence** — while a given legacy file's behaviour is being ported, both it and its
   Python/JS equivalent exist at once. This is expected, not duplication to clean up early.
3. **Retirement** — once a legacy file's ported equivalent is implemented **and** verified
   against it, that specific legacy file may be deleted. Retire files one at a time as their
   port is verified — never delete the whole folder preemptively, and never delete a file
   whose port hasn't been verified yet.

If a legacy file is missing from `legacy files/`, stop and ask for it — do not reconstruct
it from git history or any other source.

### UI fidelity

The visual design must be reproduced exactly.

`Styles.html` is the visual contract — a hand-conversion of a Tailwind reference page
into plain CSS on the same class names. Port it across rather than rebuilding it, and
preserve the load order `Styles` → `StylesReports` → `StylesAudit`. The second and third
files define additions only and assume the first has already declared the design tokens.

`Reports.html` contains a hand-written SVG chart engine with no external library. Its
output classes are styled in `StylesReports.html`, so the two are a matched pair.
Replacing it with a charting library would change the appearance and is out of scope.

The three client modules — `Scripts.html`, `Reports.html`, `Audit.html` — share no
state. Each is a self-contained IIFE binding to element IDs declared in `Index.html`,
and they map cleanly onto three frontend route modules.

### Theming — the one sanctioned exception (added 2026-09-21)

`frontend/src/styles/theme.css` is the **only** file permitted to override the ported
contract, and it exists so that the contract does not have to be edited. Load order is
now `tokens` → `reports` → `audit` → `app` → `theme`.

- `tokens.css`, `reports.css`, `audit.css` and `app.css` remain **byte-identical** ports.
  A theme is expressed by overriding them from `theme.css`, never by changing them.
  Enforce it: `git diff --exit-code` over those four must pass on any theming change.
- Two rules `theme.css` keeps, both mechanically checkable. Every rule outside its
  `:root` light block is either `[data-theme="dark"]`-prefixed or one of its own new
  classes — so light mode can only change where a change was intended. And it uses no
  `!important`: the `[data-theme="dark"]` prefix adds enough specificity on its own.
- **The neutral scale tokens are inverted in dark mode** — `--white` resolves to the
  darkest surface, `--slate-900` to the lightest ink. They denote **rank, not hue**, and
  the ordering is preserved, so every existing rule of the form
  `{background:var(--white);color:var(--slate-900)}` keeps correct contrast with nothing
  written for it. Hue tokens (gold, navy, emerald, amber, blue, indigo, rose, purple) are
  never inverted: colour *meaning* must not shift between themes.
- **The heatmap ramp lives in `theme.css` as `--heat-0`…`--heat-4` and nowhere else.**
  `reports.css`'s legend gradient and `charts.js`'s `heatColor()` both read those, so the
  legend cannot drift from the cells it describes. The ramp runs light→dark on a light
  page and dark→light on a dark one; the invariant is that more metal always reads as
  more salience against the ground.

**One deliberate departure from "reproduced exactly":** the KPI and summary cards were
restyled to `RMAS_PORT_LEDGER.html`'s tile treatment in **both** themes, on an explicit
instruction (2026-09-21). It is opt-in — the markup carries `tile-grid`/`tile` alongside
the legacy classes and `theme.css` styles the compound selectors — so deleting one word
from five templates reverts it.

## Session Logs

Development history is recorded one folder per session under `sessions/`, not a single
rolling log file:

```
sessions/
├── 2026-09-19_rmas-legacy-review/
│   └── session.md
├── 2026-09-19_postgres-schema/
│   └── session.md
```

* Folder naming: `YYYY-MM-DD_short-topic-slug`, so folders sort chronologically and are
  identifiable at a glance.
* One folder per session. Never split a single session's record across folders, and never
  merge two sessions into one folder.
* Each `session.md` covers: the session's goal, what happened (including implementation
  detail and errors encountered), what was achieved, and what's left for future sessions —
  using the template below.
* Preserve every session folder exactly; never delete or rewrite development history.
  Correcting a factual error in place is fine; removing an entry is not.
* No line-count ceiling — each session gets its own file, so there's nothing to archive or
  trim.

### `session.md` template

```markdown
# Session: <topic>

Date: YYYY-MM-DD

Goal: <what was asked for>

## What happened
<chronological account, including implementation detail>

## Errors / issues encountered
<anything that went wrong and how it was handled>

## Achievements
<what was actually delivered>

## Future things to implement / open questions
<what's left, and any decisions still pending>
```

