# Build Prompt — Audit Log Page

Paste the section below into a chat with the RMAS source attached. Everything was
read out of the current build; nothing is inferred.

**This page is administrator-only and carries the system's compliance record.**
It is the one module where an authorisation mistake is a serious problem rather
than a cosmetic one — the log holds user identities and full before/after data
snapshots.

---

## PROMPT

> Build the **Audit Log** page for the Royal Metal Allocation System, ported from
> Google Apps Script to Python (FastAPI) + JavaScript. **The UI and CSS must be
> visually identical to the current build** — reuse the existing class names and
> markup structure rather than rebuilding them.
>
> This page is read-only and **administrator-only**. It never writes.
>
> It is backed by an **append-only** log. No update, no delete, ever — and
> failures are recorded alongside successes, so the log answers "what was
> attempted", not merely "what happened".
>
> ---
>
> ### Source files that define this page
>
> **Backend (`.gs`)**
>
> | File | What it contributes |
> |---|---|
> | `AuditReportService.gs` | The whole read side. Public: `getAuditFilterOptions()`, `getAuditLog(filters)`, `getAuditEntryDetail(auditId)`, `getDateRevisionSummary(date)`, `diagnoseAdminAccess()`. Private: `assertAuditAccess_()`, `readAuditRows_()`, `decodeAllocationSnapshot_()`, `decodeFlowSnapshot_()`, `diffAllocationSnapshots_()`, `diffFlowSnapshots_()`, `snapshotAllocationTotals_()`, `snapshotFlowTotals_()`, `formatAuditTimestamp_()`, `previewReason_()`, `getSheetIfExists_()`. Config `AUDIT_REPORT_CONFIG`. |
> | `AuditService.gs` | The write side and identity. `AUDIT_ACTIONS`, `AUDIT_STATUS`, `getActiveUserEmail_()`, **`isAdministrator_()`**, `writeAuditEntry_()`, the snapshot builders, `getLatestRevisionNumber_()`. |
> | `Code.gs` | `getCurrentUserAccess()` — the endpoint the access gate calls first. Also `saveDailyAllocation()` / `reviseDailyAllocation()`, which produce the entries this page reads. |
> | `ValidationService.gs` | `response_()`, `appError_()`, `handleServerError_()`, `round3_()`, **`nearlyEqual_()`** (epsilon comparison used by both diffs), `normalizeSectorKey_()`. |
> | `DateService.gs` | `toDateKey_()`, `isValidDateKey_()`, `formatDisplayDate_()`, `shiftDateKey_()`, `todayKey_()`. |
> | `Config.gs` | `SHEETS.AUDIT`, `HEADERS.AUDIT` (the 13 columns), `ADMIN_EMAILS`, `NON_ADMIN_EMAILS`. |
>
> **Frontend (`.html`)**
>
> | File | What it contributes |
> |---|---|
> | `Index.html` | Markup for `<section id="view-audit">` (lines 730–855) — the access gate, filter bar, KPI strip and table. Plus the shared **`#auditModal`** near the end of `<body>`, which is `.modal__box--wide`. |
> | `Audit.html` | All client logic, a self-contained IIFE sharing no state with `Scripts.html` or `Reports.html`. Key functions listed below. |
> | `Styles.html` | Tokens, fonts, `.card`, `.btn`, `.modal`, `.access-gate`, `.chip`. Loads first. |
> | `StylesReports.html` | `.filter-bar`, `.summary-strip`, `.summary-stat`, `.history-table`, `.empty-state`, `.truncation-note`. Loads second. |
> | `StylesAudit.html` | Everything audit-specific: `.audit-badge--save/--revise/--blocked/--failed/--unauth`, `.status-dot--success/--blocked/--failed`, `.audit-id`, `.rev-chip`, `.reason-text`, `.detail-meta`, `.detail-reason`, `.detail-section`, `.diff-wrap`, `.diff-table`, `.cell-before`, `.cell-after`, `.is-changed`, `.row-added`, `.row-removed`, `.snapshot-note`, `.diff-legend`. Loads third. |
>
> `Audit.html` functions: `checkAccess()`, `applyAccess()`, `ensureOptions()`,
> `fillSelect()`, `populateFilters()`, `applyQuickRange()`,
> `updateAuditFilterCount()`, `auditFilters()`, `loadAuditLog()`,
> `renderAuditLog()`, `openDetail()`, `renderDetail()`, `metaItem()`,
> `allocationDiffTable()`, `flowDiffTable()`, `fieldLabel()`, `actionBadge()`,
> `statusDot()`, `exportAuditLog()`, `resetFilters()`, `bind()`.
>
> ---
>
> ### Access gating — implement this first
>
> Two layers, and **the server one is the real protection**.
>
> **Client gate (convenience).** On load, `checkAccess()` calls
> `getCurrentUserAccess()` and reads `data.isAdmin`. `applyAccess()` then toggles
> three things: the nav tab `#tabAudit` (hidden for non-admins), `#auditGate` (the
> access-required card, shown for non-admins), and `#auditContent` (hidden for
> non-admins). A failure handler defaults `isAdmin` to **false** — fail closed.
>
> It also sets the header role pill `#hdrRole` to `role-pill--admin` / "Admin" or
> `role-pill--user` / "User". Note this is a **separate indicator from Date
> Status**: Date Status reports whether the selected date can be saved, Role
> reports who you are.
>
> The gate text reads: *"The audit log contains user identities and full data
> snapshots, so it is restricted to authorized administrators. Contact your
> administrator if you need access to this record."*
>
> **Server gate (the actual control).** `assertAuditAccess_()` runs at the top of
> **every** audit endpoint — `getAuditFilterOptions`, `getAuditLog`,
> `getAuditEntryDetail`, `getDateRevisionSummary`. It resolves the caller's email,
> checks `isAdministrator_()`, and throws `NOT_AUTHORIZED` with *"The audit log is
> restricted to authorized administrators."* Hiding the tab is never the
> protection.
>
> When `getAuditLog` returns code `NOT_AUTHORIZED`, the client sets `isAdmin` to
> false and re-applies the gate — so a revoked admin loses the view mid-session.
>
> Remember the **deny list always wins**: an email in `NON_ADMIN_EMAILS` is not an
> administrator even if it also appears in `ADMIN_EMAILS`.
>
> ---
>
> ### 1. Filter & Query Controls
>
> A `.card.filter-bar` with grid modifier `filter-bar__grid--audit`. Hint:
> *"Refine audit entries across dates, actions, status and users"*. Applied count
> in `#auFilterCount`.
>
> | Control | ID | Notes |
> |---|---|---|
> | Allocation Date From | `auFrom` | `<input type="date">`. Filters on **allocation date**, not timestamp. |
> | Allocation Date To | `auTo` | Reversed range is **swapped** server-side. |
> | Action Type | `auAction` | `"All actions"` default. Options come from the data, not a hard-coded list. |
> | Status | `auStatus` | `"All statuses"` default. Likewise data-driven. |
> | User | `auUser` | `"All users"` default. Distinct emails found in the log. |
> | Reset | `auReset` | Restores suggested range and clears selects. |
> | Apply Filters | `auApply` | `.btn--primary` with tick glyph. |
>
> **Filter options are fetched once** by `ensureOptions()` →
> `getAuditFilterOptions()`, which scans the log and returns:
>
> - `actions[]`, `statuses[]`, `users[]` — distinct values, sorted
> - `entryCount`, `minDate`, `maxDate`
> - `suggestedFrom` / `suggestedTo` — a **90-day** window
>   (`DEFAULT_RANGE_DAYS`) counted back from the **latest allocation date in the
>   log**, not from today, clamped so it never precedes the earliest entry
> - `sheetExists`
>
> `populateFilters()` fills the three selects via `fillSelect()` and seeds the
> date inputs from the suggested range.
>
> **Critical date-filter rule.** An entry with **no allocation date** — a hard
> failure that occurred before the date was resolved — must **never be excluded by
> the date window.** Apply the from/to comparison only when
> `allocationDateKey` is present. Dropping these would hide exactly the failures
> the log exists to record.
>
> `auditFilters()` sends `fromDate`, `toDate`, `actionType`, `status`, `user`, and
> hard-codes `search: ''` with the comment *"the Search field was removed"*. The
> backend still supports `search` across audit ID, user, reason, request ID and
> action type. **Keep the parameter; do not surface the control.**
>
> ---
>
> ### 2. KPI cards — five
>
> All from `data.summary.counts`. These are **counts, not weights** — render as
> plain integers, no decimals.
>
> | # | Card | Value ID | Sub-line | Counts |
> |---|---|---|---|---|
> | 1 | **Entries** (navy) | `auStatTotal` | *"matching the filters"* | every matched entry |
> | 2 | **Successful** (green) | `auStatSuccess` | *"saves and revisions"* | `status === 'SUCCESS'` |
> | 3 | **Blocked** (amber) | `auStatBlocked` | *"duplicates and refusals"* | `status === 'BLOCKED'` |
> | 4 | **Failed** | `auStatFailed` | *"errors and rollbacks"* | `status === 'FAILED'` |
> | 5 | **Revisions** | `auStatRevisions` | *"administrator edits"* | `actionType === 'REVISE'` |
>
> **Counts are computed over the full matched set, before truncation** — so the
> KPIs stay accurate even when the table shows only the first 500 rows. The three
> status counts are mutually exclusive and sum to the total; **Revisions overlaps
> them** and must not be added in.
>
> ---
>
> ### 3. Audit Log table — nine columns
>
> A `.card.panel` headed **"Audit Log"** with chip `#auRowChip` → `"N entries"`
> (the *returned* count).
>
> | Column | Source | Rendering |
> |---|---|---|
> | Timestamp | `timestampDisplay` | `.date-cell`; em-dash when absent |
> | Allocation Date | `allocationDateDisplay` | `'Mon, 17-Aug-2026'`, or `—` when the entry has no date |
> | Action | `actionType` | `actionBadge()` — see below |
> | Rev. | `revisionNumber` | `> 0` → `<span class="rev-chip">#N</span>`; otherwise `<span class="rev-chip rev-chip--original">Original</span>` |
> | User | `userEmail` | plain text |
> | Reason | `reasonPreview` | `.reason-text`, truncated server-side to **140 chars** (`MAX_REASON_PREVIEW`) with an ellipsis |
> | Status | `status` | `statusDot()` — see below |
> | Audit ID | `auditId` | `<span class="audit-id">` |
> | Detail | `hasSnapshots` | **"View changes"** button, or **"No snapshot"** disabled |
>
> **`actionBadge(action)`** maps the action to a CSS modifier and replaces
> underscores with spaces for the label:
>
> | Action | Class |
> |---|---|
> | `SAVE` | `audit-badge--save` |
> | `REVISE` | `audit-badge--revise` |
> | `BLOCKED_DUPLICATE` | `audit-badge--blocked` |
> | `FAILED_SAVE`, `FAILED_REVISION` | `audit-badge--failed` |
> | `UNAUTHORIZED_REVISION` | `audit-badge--unauth` |
> | anything else | `audit-badge--other` |
>
> **`statusDot(status)`**: `SUCCESS` → `status-dot--success`, `BLOCKED` →
> `status-dot--blocked`, **everything else** → `status-dot--failed`.
>
> **Sort:** timestamp descending, tie-broken by sheet row number descending —
> newest first, and stable for entries written in the same second.
>
> **Truncation, not pagination.** This page has **no pager**. The server returns
> at most **500 rows** (`MAX_ROWS_RETURNED`) and sets `truncated`. When true,
> `#auTruncated` reads: *"Showing the most recent N of M matching entries. Narrow
> the date range or filters to see older entries."* Unlike the history pages, this
> flag is **genuinely wired** and does fire.
>
> **Empty state** `#auEmpty`: *"No audit entries found"* / *"Adjust the date range
> or filters and apply again."*
>
> **Row clicks are delegated**: one listener on `#auBody` catches
> `.js-audit-detail` and reads `data-audit-id`.
>
> ---
>
> ### 4. "View changes" — the audit detail modal
>
> This is the heart of the page. Clicking **View changes** calls `openDetail()`,
> which shows the overlay *"Loading the snapshot comparison…"* and calls
> **`getAuditEntryDetail(auditId)`**. The row payload deliberately excludes
> snapshots — they are fetched only when asked for.
>
> The button is **disabled and labelled "No snapshot"** when `hasSnapshots` is
> false, which is the case for blocked and failed entries where nothing was
> captured.
>
> #### How the server builds the comparison
>
> 1. `assertAuditAccess_()` — admin re-check.
> 2. Reject a blank ID with `INVALID_AUDIT_ID`, *"No audit entry was specified."*
> 3. Scan `readAuditRows_()` for a matching `auditId`; if absent return
>    `AUDIT_ENTRY_NOT_FOUND`, *"That audit entry no longer exists in the log."*
> 4. Decode four JSON snapshot columns via `decodeAllocationSnapshot_()` and
>    `decodeFlowSnapshot_()`. **Snapshots use short keys** to keep the cell small:
>    `p` priority, `s` sector, `pu` purity, `pr` previousRequirement,
>    `tr` todayRequired, `al` alloted, `bl` balance. Decoding is wrapped in
>    try/catch — a malformed snapshot logs and yields an empty array rather than
>    failing the request.
> 5. `diffAllocationSnapshots_()` and `diffFlowSnapshots_()` build the comparison.
> 6. Compute totals for all four snapshots and count changed sectors.
>
> #### Diff semantics — match these exactly
>
> Both diffs **union** the before and after sector sets, keyed on
> `normalizeSectorKey_()`, preserving first-seen order (before rows first). Each
> entry carries:
>
> - `before` / `after` — the row, or `null` when absent on that side
> - `onlyBefore` — present before, gone after → **sector removed**
> - `onlyAfter` — absent before, present after → **sector added**
>
> Allocation compares four fields — `previousRequirement`, `todayRequired`,
> `alloted`, `balance` — producing a `changed` map plus `anyChange`. Flow compares
> the single `acquired` field into a boolean `changed`.
>
> **Comparison uses `nearlyEqual_()`, never `==`.** The epsilon is `0.0005`, half
> of the third decimal place. Two weights that differ only by float noise are not
> a change.
>
> **When a sector exists on only one side, every field counts as changed.** That
> is deliberate: an added or removed sector is a change in all its values.
>
> #### What the modal renders — `renderDetail()`
>
> Target `#auditModal` (`.modal__box--wide`), title
> **`"Audit Entry — <allocation date>"`**.
>
> **Meta grid** (`.detail-meta`, via `metaItem()`), eight items: Action (badge),
> Status (dot), Revision (`#N` or *"Original save"*), User, Timestamp, Audit ID,
> Request ID, and **Sectors changed** → `"N allocation · M flow"`.
>
> **Reason block** (`.detail-reason`) — only when a reason exists. This is the
> **full** reason, not the 140-character preview.
>
> **Snapshot notes** (`.snapshot-note`), whichever applies:
> - No before, has after → *"This is an original save, so there is no earlier
>   state to compare against. The "before" columns are empty by design."*
> - Neither → *"This entry records a blocked or failed action, so no data snapshot
>   was captured. Nothing in either master sheet was changed."*
>
> **Section: "Allocation Data"** — rendered only when `allocationDiff` is
> non-empty. Head note: `"N sector(s) changed"`. A `.diff-table` in a `.diff-wrap`
> with **nine columns** — Sector, then four before/after pairs:
>
> ```
> Sector | Prev. Req. (before) | Prev. Req. (after)
>        | Required (before)   | Required (after)
>        | Alloted (before)    | Alloted (after)
>        | Balance (before)    | Balance (after)
> ```
>
> - "before" headers carry `.group-before`, "after" carry `.group-after`
> - Value cells carry `.cell-before` / `.cell-after` plus `.num`, and
>   **`.is-changed` when that specific field changed**
> - Row class `.row-added` when `onlyAfter`, `.row-removed` when `onlyBefore`,
>   with an inline `audit-badge--save` "added" or `audit-badge--failed` "removed"
>   beside the sector name
> - A `null` value renders as an em-dash, not `0.000` — absence and zero are
>   different facts
> - **`<tfoot>` totals row**, labelled `"Totals (B → A rows)"` so a change in row
>   count is visible, with summed before/after for all four fields
>
> Below it a `.diff-legend` with three keys: *Changed value* (`#fdf0d8`, border
> `#f2ddb0`), *Sector added* (`#e3f5ec`), *Sector removed* (`#fbe4e4`).
>
> **Section: "Metal Flow Data"** — rendered only when `flowDiff` is non-empty.
> Head note: `"N sector(s) changed"`. Three columns — Sector, Acquired (before),
> Acquired (after) — with the same `.is-changed`, `.row-added`, `.row-removed`
> treatment and a totals footer.
>
> **Dismissal:** `#auditModalClose`, a backdrop click on `#auditModal`, or the
> **Escape** key.
>
> ---
>
> ### Endpoint contracts
>
> **`GET /api/audit/filter-options`** → `actions[]`, `statuses[]`, `users[]`,
> `entryCount`, `minDate`, `maxDate`, `suggestedFrom`, `suggestedTo`,
> `sheetExists`
>
> **`GET /api/audit/log`** — request `fromDate`, `toDate`, `actionType`, `status`,
> `user`, `search`, `limit`. Response:
> - `rows[]` — `auditId`, `allocationDateKey`, `allocationDateDisplay`,
>   `actionType`, `revisionNumber`, `userEmail`, `timestampDisplay`,
>   `reasonPreview`, `requestId`, `status`, `hasSnapshots`
> - `summary` — `recordCount`, `returnedCount`, `truncated`,
>   `counts{total, success, blocked, failed, revisions}`
>
> **`GET /api/audit/entry/{auditId}`** → `auditId`, `allocationDateKey`,
> `allocationDateDisplay`, `actionType`, `revisionNumber`, `userEmail`,
> `timestampDisplay`, `reason`, `requestId`, `status`, `hasBefore`, `hasAfter`,
> `allocationDiff[]`, `flowDiff[]`,
> `totals{beforeAllocation, afterAllocation, beforeFlow, afterFlow}`,
> `changedSectors`, `changedFlowSectors`
>
> Limits: `MAX_ROWS_RETURNED = 500`, `DEFAULT_RANGE_DAYS = 90`,
> `MAX_REASON_PREVIEW = 140`.
>
> ---
>
> ### Rules that must hold
>
> 1. **Every audit endpoint re-checks admin status server-side.** Hiding the tab is
>    not protection. Fail closed on any error.
> 2. **The deny list beats the admin list.**
> 3. **The log is append-only.** No update path, no delete path, at any layer.
> 4. **Entries with no allocation date are never filtered out by the date window.**
> 5. **Failures and blocks are first-class entries**, not errors to suppress.
> 6. **Snapshot diffs use epsilon comparison** (`0.0005`), never `==`.
> 7. **A missing value renders as an em-dash, never as `0.000`.**
> 8. **Snapshots load on demand**, never in the list payload.
> 9. **Weights are exact** — integer grams stored, `Decimal` at the boundary,
>    three decimals displayed. Counts are integers.
> 10. **The list shows a truncation note, not a pager.**
> 11. Do not reintroduce the removed Search box.
> 12. A malformed snapshot must degrade to an empty diff, never break the request.

---

## Notes for you, not part of the prompt

**`getDateRevisionSummary(date)` and `diagnoseAdminAccess()` are public endpoints
that no page calls.** The first returns the revision history for a single
allocation date — useful if you ever want a "this date has been revised N times"
badge on the Daily Allocation screen. The second is an access-troubleshooting
helper. Decide whether either survives the port.

**The reason preview is truncated server-side at 140 characters, but the modal
shows the full text** from a second fetch. That is the right split — just make
sure the port doesn't "helpfully" send the full reason in the list payload, since
reasons can be long and the list can carry 500 rows.

**This is the only page where `truncated` actually works.** Both history pages
hard-code it to `false`; here it is computed as `matched.length > limit` and
drives a visible note. If you standardise the envelope across pages during the
port, fix the history pages up to this behaviour rather than flattening this one
down to theirs.
