# Session: Date revision summary and access diagnostics

Date: 2026-09-21

Goal: Port the two remaining legacy read functions flagged in `RMAS_PORT_LEDGER.html` —
`getDateRevisionSummary()` (who committed an allocation date, and whether it has been
revised) and `diagnoseAdminAccess()` (why the server treats a caller the way it does).

## What happened

### The dependency, raised before any code was written

The ledger recorded both as "depends on the revision path existing first". That is half
true and was worth settling up front: the port has no revise route, `ACTION_REVISE` is
never written, and all 37 live audit rows carry `revision_number = 0`, so a "revised N
times" badge would read zero forever.

Resolved by widening slightly: legacy's payload **already** carries
`originallySavedBy`/`originallySavedAt` beside the revision fields, so rendering the whole
thing is useful today (35 live `SAVE` rows) and complete the moment the revise path lands.
No rework. `diagnoseAdminAccess()` turned out not to depend on revisions at all.

### The finding that shaped Feature A

`getDateRevisionSummary()` is **the one function in `AuditReportService.gs` that
deliberately does not call `assertAuditAccess_()`** — that guard exists at `:27` and is
called at `:307`, `:360` and `:451`, but not at `:517`. Its docstring says why: *"Safe for
every user: returns counts and timestamps only, never snapshots."*

Every `/audit` endpoint in the port is `require_admin`, and `frontend/src/api/audit.js`
converts a 403 into `revokeAccess()`. A new route there would have silently made the badge
admin-only and read an operator's legitimate response as "your access was revoked". So the
summary was folded into the existing `GET /allocations/{date}` instead — already
operator-visible, already fetched by `load()`, no second round-trip, and
`getAllocationForDate` returns `response.json()` raw so the frontend API layer needed no
change at all.

### Feature A — implementation

- **`repository/audit_repo.py`** — new `get_success_entries_for_date()`. Deliberately not
  the two existing functions, both verified to have zero callers anywhere:
  `get_entries_for_date` is unfiltered on status (a `FAILED_REVISION` would inflate the
  count) and `get_latest_revision_number` is `MAX()` over the date, which is **not**
  legacy's "the newest revision's own number". Both left untouched for the revise path.
  Ordered by `action_timestamp` **then `audit_row_id`** — `datetime('now')` has one-second
  granularity, so without the tie-break "the first save of this date" is not stable.
- **`services/audit_report_service.py`** — `DateRevisionSummary` + `get_date_revision_summary()`.
  One query, partitioned in memory as legacy does. Rows arrive oldest-first, so `saves[0]`
  is the original and `revisions[-1]` the newest — legacy sorts its two lists in opposite
  directions for exactly this reason.
- **`schemas/audit.py` / `schemas/allocation.py`** — `DateRevisionSummaryResponse`, carried
  on the allocation response.
- **`routers/allocations.py`** — mapped **outside** the `is_administrator` block, with a
  comment saying so, so nobody later "tidies" it inside. Timestamps formatted with the
  existing `format_audit_timestamp()`.
- **`frontend/src/views/allocation.js`** — `revisionNoteHtml()` + `revisionNotice()`, and a
  one-line dispatch in `renderNotices()`. Pushed first in `load()`'s notice array.

**The CSS was already written and had never been used.** `.revision-note` /
`.revision-note__icon` sit in `audit.css` under a banner comment reading verbatim
`/* ------------------- REVISION NOTICE ON DAILY SCREEN -------------- */`. Zero usages
anywhere — written in anticipation of this feature and finally wired up. No CSS was added.

### Feature B — implementation

Legacy's `diagnoseAdminAccess()` returned `configuredAdmins` (the entire `ADMIN_EMAILS`
array) and `forcedNonAdmins` (the entire deny list). **CLAUDE.md rule 10 forbids both**
outright. Legacy could afford them because the function ran only from the Apps Script
editor — *"run this manually"*, per its own docstring — and that containment does not
survive becoming an HTTP route.

So the port keeps the diagnostic logic and drops the payload: self only, no roster, and
**no subject parameter** (legacy's `debugScreenFlags` let an admin inspect another user;
that is "any other account's scope").

- **`repository/sector_repo.py`** — `get_party_names()`, `get_flow_sector_names()`.
- **`services/scope_service.py`** — `AccessDiagnosis` + `diagnose_access()`. Pure, no
  `Session`, which also keeps it clear of the import cycle below.
- **`routers/deps.py`** — `get_current_scope()`.
- **`routers/auth.py`** — `GET /auth/access-diagnostics`, gated by `get_current_user`, not
  `require_admin`: the question is "why can't *I* see the Audit Log", so gating on admin
  would refuse exactly the people who need it.

**The trap, and it is a real one:** `build_scope()` leaves `flow_sector_ids = None` for
**administrators** as well as for operators with no explicit grants. Testing the fallback
branch before `unrestricted` would tell every administrator they have no flow grants. Two
tests pin the branch order. The fallback string is verbatim legacy
(`StagingService.gs:854`), down to the plain hyphen — and since `user_flow_scope` is empty
for every live account, it is the string everyone actually reads.

## Errors / issues encountered

- **Wrong column name.** Wrote `FlowSector.flow_sector_name`; the column is `sector_name`.
  Caught by reading the model before running anything.
- **A circular import avoided rather than hit.** `repository/sector_repo.py` imports
  `UserScope` from `services/scope_service.py`, so the obvious "let scope_service resolve
  the names" design would crash on import. Composition went into `routers/deps.py` and
  `routers/auth.py` instead, following the existing pattern of routers calling repositories
  directly (`routers/auth.py`, `routers/allocations.py` already do).
- **A stubborn uvicorn worker.** The probe server kept holding the database copy after the
  first `taskkill`; a second process was still listening. Killed by looking up the
  listening PID from `netstat` rather than by image name.

## Achievements

- Both features working end to end, **246 → 270 tests passing**.
- Verified against the real database. `2026-09-19` has two `SAVE` rows, 16:10:14 and
  16:11:25; the endpoint returns **16:10:14** — the "original save is the first, not the
  latest" rule proven on live data, not just in a fixture.
- The revision branch, which cannot occur naturally yet, was exercised by forcing a
  `REVISE` row into a scratchpad **copy**: it rendered `revision_count 1`,
  `latest_revision_number 1`, the author, the timestamp and the full reason.
- Rule 10 proven, not just intended: an operator's diagnostics response contains no other
  account's address, and a `?email=`/`?subject=` probe changes nothing. Both are tests.
- The admin branch-order trap proven: an administrator reads *"Unrestricted — an
  administrator sees every party's flow rows"*, never the fallback string.
- Query is index-backed — `EXPLAIN QUERY PLAN` shows
  `SEARCH ... USING INDEX idx_audit_date`.
- Live database untouched throughout: 37 audit rows before and after, zero probe rows, and
  the only action types present are still `SAVE`, `SUBMIT_REQUIREMENT`,
  `BLOCKED_RESUBMISSION`.

### Decisions taken this session

1. Date **history**, not a bare revision count — render legacy's whole payload.
2. **Visible to everyone**, matching legacy's explicit contract; folded into the allocation
   response rather than added under `/audit`.
3. The **full reason and the author's email go to everyone**, legacy verbatim.
4. `.revision-note` for the treatment — the class the authors wrote for this screen.
5. Diagnostics are **self-only**: no roster, no other account, no subject parameter.
6. The `is_active` hole (below) is **logged, not fixed**.

## Future things to implement / open questions

- **A real auth hole, found while tracing and deliberately not fixed.** `login` refuses an
  inactive account (`routers/auth.py`), but `get_current_user` (`routers/deps.py`) never
  re-checks `is_active`, so **someone deactivated mid-session keeps full access until their
  cookie expires**. One line to fix, but it changes authentication behaviour for every
  endpoint and deserves its own commit and test. Diagnosis line 4 ("This account is marked
  inactive") exists precisely because that state is reachable. **Should be added to the
  open-question register.**
- **Live data discrepancy, surfaced not resolved.** The new diagnostic reports
  `pc2.rcpl@gmail.com` → parties `['Royal Chain']`, while legacy `Config.gs:73` mapped that
  same email to `['Aalishaan']`. Either a deliberate reassignment during the migration or a
  transcription error. Confirm before anyone relies on that operator's scope.
- **The revision half is fixture-only** until the revise path is built — still the largest
  gap in the port, and still the thing that would make this badge fully useful.
- **Dead code kept deliberately:** `audit_repo.get_latest_revision_number()` and
  `get_entries_for_date()`, both with zero callers. The revise path will want the first.
- `getCurrentUserScope`, `getOperatorRequirementForDate` and `getStagedRequirementsForDate`
  remain unported; CSV export and toasts likewise.
- Unchanged from earlier sessions: audit and staging timestamps are stored UTC while the
  app timezone is Asia/Kolkata, so both new timestamp fields display UTC exactly as the
  audit log does; `ruff`/`mypy` are still missing from `.metal`.
- **Not seen in a browser** — verified at the source, API and database level only, per the
  standing preference. `.revision-note`'s rendering has not been looked at.
