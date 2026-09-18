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
- **PostgreSQL** — production database
- **pytest** + **httpx** — testing
- **Decimal** (`decimal.Decimal`) — every weight, everywhere

**Do not introduce new dependencies unless necessary.** If a new package is genuinely
required, say why and what it replaces before adding it.

**Explicitly avoid:**

- `float` for any weight, requirement, allotment or balance — see Critical Rules
- Pandas for request-path logic (acceptable in offline migration scripts only)
- ORM-level lazy loading in report queries; be explicit
- Raw SQL outside `repository/`
- Any Google API dependency in the new stack — the port exists to remove it

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

1. **Never use `float` for weights.** Use `Decimal` in Python and `NUMERIC(12, 3)` in
   PostgreSQL. This system reconciles physical gold; float drift is a real financial
   error, not a rounding cosmetic.
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
    they are different sector sets with different sector counts.

### Known legacy inconsistencies

Carry these forward as *questions*, not as ported behaviour:

- `RANGES.ALLOCATION_SECTORS` is `A7:C25` (**19 rows**) while
  `EXPECTED.ALLOCATION_ROWS` is **21**. `STRICT` is `false`, so the legacy app logs a
  warning and uses whatever the sheet contains. The true sector count must be confirmed
  during migration.
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
