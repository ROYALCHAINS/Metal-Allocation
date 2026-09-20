# Session: Audit Log module

Date: 2026-09-20

Goal: read `PROMPT_audit_log.md` and implement the Audit Log page.

## What happened

### The stylesheet had never been ported

`StylesAudit.html` — the third file in the load order CLAUDE.md section 7 calls
load-bearing — was still sitting unported in `legacy files/`. Every class the
page needs lived there: `.audit-badge--*`, `.status-dot--*`, `.audit-id`,
`.rev-chip`, `.reason-text`, `.detail-meta`, `.detail-reason`,
`.detail-section`, `.diff-wrap`, `.diff-table`, `.cell-before` / `.cell-after`,
`.is-changed`, `.row-added` / `.row-removed`, `.snapshot-note`, `.diff-legend`.

Ported verbatim to `frontend/src/styles/audit.css` (227 lines, `<style>` tags
stripped, header comment added) and linked in `index.html` **between**
reports.css and app.css, preserving Styles → StylesReports → StylesAudit. Every
`var(--token)` it references was checked against tokens.css; all resolve.

It also carries `.modal__box--wide{width:min(1080px,96vw)}`, which overrides the
760px in tokens.css — so the diff table gets the width it was designed for. And
`.page`/`.app-header__inner`/`.view-nav__inner` widen to 1840px, which now
applies across the whole app as legacy intended.

### Backend

- **`services/audit_report_service.py`** (new) — the read side, ported from
  `AuditReportService.gs`. Snapshot decoding from the abbreviated keys
  (`p/s/pu/pr/tr/al/bl`, `ac` for flow), the union diff, totals,
  `preview_reason()`, `format_audit_timestamp()`. Kept separate from
  `audit_service.py`, which remains write-only.
- **`repository/audit_repo.py`** — added `query_log`, `count_by_status`,
  `distinct_filter_values`, `date_bounds`, `total_entry_count`, `get_entry`.
  Still INSERT-only for writes: no update, no delete, at any layer.
- **`routers/audit.py`** — rewritten. Three endpoints, each behind
  `require_admin`: `/audit/filter-options`, `/audit`, `/audit/entry/{id}`.
- **`schemas/audit.py`** — rewritten for the diff payload.

Rules implemented and tested:

| Rule | How |
|---|---|
| Admin re-checked server-side on **every** endpoint | `require_admin` on all three; tested per-endpoint, not just the list |
| Deny list beats an admin grant | `is_administrator()` already did; now pinned by test |
| Snapshots load on demand | the list payload has no diff at all; asserted in a test |
| Counts over the **full** matched set | `count_by_status` runs before the limit; `record_count` vs `returned_count` |
| Revisions **overlap** the status counts | counted separately, never added in; asserted |
| Truncation, not pagination | `truncated` computed and surfaced as a note; no pager |
| Epsilon comparison, never `==` | `nearly_equal_g`, which in integer grams is exact equality |
| One-sided sector = every field changed | forced in `_diff`; asserted for both added and removed |
| Malformed snapshot degrades to empty | `_load` catches and logs; four bad-input cases asserted |
| Missing value is an em-dash, not `0.000` | `None` through the schema, `weight()` in the view |
| Search parameter kept, control not surfaced | `search` filter implemented; no input rendered |

### Frontend

- **`api/audit.js`** (new) — moved the two audit calls out of `api/reports.js`
  (one module per router). Adds `AuthError`, so a 403 mid-session re-applies the
  access gate instead of showing an error banner.
- **`views/audit.js`** — rewritten: access gate, filter bar with the three
  data-driven selects, five KPI cards, the nine-column table with action badges
  / revision chips / status dots, the truncation note, the empty state, and the
  detail modal with both diff tables, totals footers and the legend. Row clicks
  are delegated through one listener on `#auBody`.
- Filters apply on change and there is no Apply button, consistent with the
  rest of the app.

## Errors / issues encountered

1. **Left junk in a constant.** `['alloted', 'Alloted', 'balance_kg' && 'alloted_kg']`
   — a stray `&&` that happened to evaluate to the right string. Caught on
   re-read and removed. It would have worked, which is what makes it bad.
2. **A leaking Escape listener.** The first version bound `keydown` on both the
   container and `document`, so every visit to the tab stacked another document
   listener. Replaced with one self-removing listener that detaches when the
   modal node is no longer connected.
3. **Calling the endpoint directly tripped over `Query(...)`.** `limit`'s
   default is a FastAPI `Query` object, which is only resolved through the
   framework — the direct-call verification script had to pass `limit`
   explicitly. Harness artefact, not a production bug.
4. Duplicated `.legend-swatch` sizing in app.css that reports.css already
   declares; trimmed to the two properties actually needed.

## Achievements

- 199 tests pass, up from 169. Two new files:
  - `tests/test_audit_diff.py` (14) — snapshot decoding and diff semantics,
    pure functions, no database.
  - `tests/test_audit_access.py` (16) — the authorisation gate through real
    HTTP, parametrised across all three endpoints for anonymous, operator and
    deny-listed callers, plus truncation, counts and the preview/full-reason
    split.
- Verified against the live database: 35 audit entries, filter options
  correctly suggesting 2026-09-01 → 2026-09-21, status counts partitioning the
  total, and a real snapshot diff rendering 21 allocation and 21 flow rows.
- Every field the view reads was cross-checked against the live payload (9 + 19
  + 5 + 4 + 5 fields, none missing), and every CSS class it uses against the
  four stylesheets (84 classes, only the `js-` behaviour hook unstyled, as
  intended).
- All 17 frontend modules pass `node --input-type=module --check`.
- No browser automation used.

## Future things to implement / open questions

Three contradictions surfaced, none resolved silently:

1. **Rule 4 is currently unreachable.** The page spec says an entry with *no*
   allocation date must never be excluded by the date window — a hard failure
   recorded before the date was resolved. The filter in `audit_repo` honours
   that. But the supplied `schema.sql` makes `allocation_date` NOT NULL with a
   date-format CHECK, so **no such row can be written in the first place**.
   Verified: both `None` and `""` are rejected. Pinned by
   `test_undated_entries_cannot_exist_in_this_schema`. Resolving it means a
   migration to make the column nullable — a decision, not a code change.
2. **Audit timestamps are stored in UTC but the app timezone is Asia/Kolkata.**
   `action_timestamp` defaults to SQLite's `datetime('now')`, which is UTC, so
   the displayed time is 5h30m behind local. Flagged in
   `format_audit_timestamp()`. Fixing it means changing how the column is
   written, not how it is displayed.
3. **`role-pill--user` is styled nowhere.** Legacy's `Audit.html` writes that
   modifier but `StylesAudit.html` only ever defines `role-pill--operator`, so
   in legacy the non-admin pill is unstyled. Resolved towards the stylesheet
   (the visual contract) — `appHeader.js` now emits `--operator` and the label
   reads "Operator". Called out in a comment at the site.

Also still open, unchanged from earlier sessions:

- `getDateRevisionSummary()` and `diagnoseAdminAccess()` are legacy endpoints no
  page calls. Not ported. The first could back a "this date has been revised N
  times" badge on the Daily Allocation screen.
- Fulfilment rate differs between Allocation History and the Dashboard, by
  design.
- `summary.truncated` is hard-coded `false` on both history pages. **The audit
  page now does it properly** — the spec's own note says to fix the history
  pages up to this behaviour rather than flattening this one down to theirs.
- A duplicate `request_id` errors where CLAUDE.md rule 12 describes replaying.
- The revise path has no idempotency guard.
