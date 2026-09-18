# RMAS — Source File Reference

Per-file summary of the Royal Metal Allocation System (Apps Script build `5H`).
20 files, ~10,280 lines. Use this to locate the right file before reading it.

**Load order matters.** Apps Script has no module system — every `.gs` file shares one
global namespace, and the HTML files are stitched together by `include()` at render
time. Styles cascade in a fixed order.

---

## Backend — `.gs` files

### `Config.gs` — 309 lines
**Single source of all configuration.** Nothing in this list may be hard-coded elsewhere.

Holds: app name and version (`5H`); `SPREADSHEET_ID` (blank = container-bound);
`ADMIN_EMAILS`; `NON_ADMIN_EMAILS` (deny list, always wins over an admin grant);
`USER_DISPLAY_NAMES`; `OPERATOR_PARTIES` and `OPERATOR_FLOW_SECTORS` (email → scope);
sheet names; cell ranges for sector definitions; header-label maps used for column
detection; canonical header rows; and the `RULES` toggle block.

Constants: `DECIMALS: 3`, `EPSILON: 0.0005`, `MAX_WEIGHT_KG: 100000`,
`TIMEZONE_FALLBACK: 'Asia/Kolkata'`, `LOCK_TIMEOUT_MS: 30000`,
`REQUEST_ID_TTL_SECONDS: 900`, `STORAGE_HOUR: 12` (dates stored at noon to defeat
DST/UTC rollover).

`getPublicConfig_()` returns a safe subset to the browser — never the admin list.

> Rule toggles currently **off** and not to be re-enabled without instruction:
> `REQUIRE_FULL_ALLOCATION`, `REQUIRE_POSITIVE_ALLOTED`, `BLOCK_OVER_ALLOCATION`,
> `OPERATOR_REQUIRED_WITHIN_ACQUIRED`.

---

### `Code.gs` — 498 lines
**Web app entry point and the two write endpoints.**

- `doGet(e)` — renders `Index.html`, sets viewport and `ALLOWALL` X-Frame mode
- `include(filename)` — inlines the Styles/Scripts partials
- `setupMetalAllocationApp()` — one-time setup/health check; creates the audit sheet,
  adds headers only to empty sheets, verifies sector definitions
- `getCurrentUserAccess()`, `getAppBootstrapData()` — identity, role and first payload
- `checkDateAlreadySaved(date)`, `getAllocationForDate(date)` — read paths
- **`saveDailyAllocation(payload)`** — the primary write. Script lock, request-ID
  idempotency via cache, validation, bulk write to both masters, audit entry
- **`reviseDailyAllocation(payload)`** — admin-only revision; requires a reason,
  captures before/after snapshots, increments the revision number

---

### `DataService.gs` — 633 lines
**All Google Sheets I/O.** Bulk reads and writes only — no row-by-row operations.
The `Example` and `Metal Allocation Working` sheets are never opened for writing.

Key functions: `getSpreadsheet_()` (cached), `getSheetOrThrow_()`,
`readAllocationSectorDefinitions_()`, `readFlowSectorDefinitions_()`,
`readPartyDefinitions_()`, `readMasterRows_()`, `readFlowMasterRows_()`,
`buildAllocationModel_(dateKey)` (assembles the screen model including carry-forward),
`buildMasterRowValues_()`, `appendBothMasters_()`, `deleteRowsForDate_()`,
`ensureHeaderRow_()`, `ensureAuditSheet_()`, `invalidateDataCache_()`.

This is where `balance = previousRequirement + todayRequired − alloted` is materialised
onto the sheet.

---

### `SchemaService.gs` — 323 lines
**Locates columns by header text rather than fixed position.**

Exists because the layout drifted: a Party column was inserted into Metal Generator
and the sector count changed, which silently broke fixed-range reads. Normalises header
labels (lowercase, punctuation stripped) and matches them against the label maps in
`Config.gs`. Caches every detected layout per execution. Writes nothing.

`describeDetectedSchema()` is the diagnostic that prints what it actually found.

> On a SQL port this file has no equivalent — an explicit schema replaces it.

---

### `ValidationService.gs` — 291 lines
**Shared helpers plus all server-authoritative validation.** The browser validates for
convenience only; nothing is written unless it passes here.

Helpers: `response_()` (the `{ok, code, message, data}` envelope every public function
returns), `appError_()`, `handleServerError_()` (logs the real stack, returns a safe
message), `round3_()`, `toNumber_()`, `fmt3_()`, `normalizeSectorKey_()`,
`nearlyEqual_()` (epsilon comparison — never `==` on weights),
`assertSignedWeight_()`, `assertValidWeight_()`.

Core: `validateAndNormalizePayload_()`, `computeTotals_()` (the balance arithmetic),
`assertSaveRules_()` (reads the `RULES` toggles), `assertRevisionReason_()`.

---

### `StagingService.gs` — 1,098 lines
**Operator scope and the submission workflow.** The largest backend file.

Defines `RECORD_TYPE` (`ALLOCATION` / `FLOW`), `STAGING_STATUS`, and the staging column
map. Resolves who may see what:

- `getUserScope_(email)` — turns config into party keys and flow sector keys
- `scopeAllows_()`, `scopeAllowsFlow_()`, `filterRowsByScope_()`,
  `filterFlowRowsByScope_()` — applied on the server to every read
- `buildSectorPartyMaps_()` — sector → party lookup

Public: `getCurrentUserScope()`, `getOperatorRequirementForDate()`,
`submitOperatorRequirements()` (writes staged rows, not masters),
`getStagedRequirementsForDate()` (admin view, aggregated by operator).

Debug: `debugScreenFlags()`, `debugStagingForDate()`.

---

### `AuditService.gs` — 207 lines
**Writes the append-only audit log.** The master sheets are never extended with audit
columns.

`AUDIT_ACTIONS`: `SAVE`, `REVISE`, `BLOCKED_DUPLICATE`, `FAILED_SAVE`,
`FAILED_REVISION`, `UNAUTHORIZED_REVISION`. `AUDIT_STATUS`: `SUCCESS`, `BLOCKED`,
`FAILED` — failures are recorded, not just successes.

Also owns identity and role resolution, which makes it load-bearing well beyond
auditing: `getActiveUserEmail_()`, `getEffectiveUserEmail_()`, `getDisplayName_()`,
`emailInList_()`, **`isAdministrator_()`**. Snapshot builders serialise before/after
state; `getLatestRevisionNumber_()` sequences revisions; `writeAuditEntry_()` appends.

---

### `AuditReportService.gs` — 557 lines
**Administrator-only, read-only audit viewer.** Writes nothing.

`assertAuditAccess_()` re-checks admin status on the server for every call — hiding the
tab in the browser is convenience, never protection.

Decodes and diffs snapshots (`diffAllocationSnapshots_`, `diffFlowSnapshots_`) so a
revision can be shown as a before/after comparison. Public: `getAuditFilterOptions()`,
`getAuditLog(filters)`, `getAuditEntryDetail(auditId)`,
`getDateRevisionSummary(date)`, plus `diagnoseAdminAccess()`.

Caps: 500 rows per response, 90-day default look-back, 140-character reason preview.

---

### `ReportService.gs` — 937 lines
**Read-only history and dashboard aggregation.** Every query is scope-filtered.

- `getHistoryFilterOptions()` — dropdown values the user is allowed to see
- `getAllocationHistory(filters)` — paged allocation rows
- `getMetalFlowHistory(filters)` — paged flow rows
- `getDashboardSummary(filters)` — KPIs plus the `byDate`, `bySector` and `byParty`
  aggregations that feed every chart

---

### `DateService.gs` — 149 lines
**All date normalisation and the carry-forward rule.** Every date in the system is a
`yyyy-MM-dd` string produced in the spreadsheet timezone.

`toDateKey_()` accepts `Date`, `yyyy-MM-dd`, `dd/MM/yyyy`, `dd-MM-yyyy`, `dd-MMM-yyyy`.

**The business rule lives here:** `previousSourceDateKey_()` — Monday looks back to
Saturday (−2 days), every other day looks back 1 day. This encodes the six-day working
week.

Also `getAppTimeZone_()`, `dateKeyToStorageDate_()`, `shiftDateKey_()`,
`formatDisplayDate_()` (`'Mon, 17-Aug-2026'`), `todayKey_()`, and the public
`calculatePreviousSourceDate()`.

---

### `DiagnosticsService.gs` — 131 lines
**Read-only layout inspection.** Run from the editor, read the execution log. Exists so
configuration can be matched to the real sheet layout instead of guessed.

`inspectMetalGeneratorLayout()`, `inspectMasterLayout()`, `inspectAllLayouts()`.

---

### `VersionCheck.gs` — 101 lines
**Detects partially-pasted or stale files.** Each file defines a build-marker function;
a missing marker means that file was never pasted or was pasted incompletely.

`checkInstalledFiles()` and `previewScopeFor(email)` (shows the resolved scope for any
address without signing in as them).

---

## Frontend — `.html` files

### `Index.html` — 935 lines
**The only full HTML document.** Everything else is injected into it.

Includes `Styles`, `StylesReports`, `StylesAudit` in the head, and the script partials
at the end. Structure: app header (selected date, previous date, status, user, role),
nav tabs with count pills, then three view containers:

- `#view-daily` — date picker, six KPI cards (previous requirement, today's required,
  acquired, alloted, remaining, closing balance), banner, allocation table, flow table,
  sticky action bar
- `#view-dashboard` — filter bar, KPI strip, chart cards
- `#view-audit` — admin-gated audit viewer

Element IDs here are the contract the three script modules bind to.

---

### `Scripts.html` — 926 lines
**Client logic for the Daily Allocation view.** IIFE, strict mode, build stamp
`RMAS-Scripts-5C.2` logged to console. Every rule here is re-validated server-side.

Rendering: `renderAllocationRows()`, `renderFlowRows()`. State: `readScreen()`,
`computeTotals()`, `recalc()` (live recalculation as figures are typed),
`updateRemainingState()`, `updateSaveState()`, `applyRoleChrome()` (hides admin-only
chrome). Lifecycle: `bootstrap()`, `loadDate()`. UI: overlay, toast, banner, modal.

Generates a client-side `uuid()` used as the request ID for idempotent saves.

---

### `Reports.html` — 1,198 lines
**Allocation History, Metal Flow History and Analysis Dashboard.** Read-only, and
independent of `Scripts.html`.

Contains a **hand-written SVG chart engine** — no charting library:

- `groupedBarChart()` — acquired vs alloted
- `lineChart()` — closing balance trend and operator flow trend
- `sectorBarChart()` — requirement vs balance per sector
- `niceMax()` — axis rounding; `fmt0()`, `fmt3()`, `fmtPct()` — label formatting

Also paging, filter wiring and CSV export for both history tables.

---

### `Audit.html` — 558 lines
**Administrator-only audit viewer.** Read-only, independent of the other two modules.
Renders the log list, the filter bar, and the before/after snapshot comparison for a
selected entry. Shows an access gate to non-admins — the real check is server-side.

---

### `Styles.html` — 769 lines
**The design system. Loads first and owns every token.**

A direct hand-conversion of a Tailwind CDN reference page into plain CSS on the same
class names, so no markup or JavaScript had to change and no compiler runs in the
browser. Marked `RMAS-Styles-7H`.

`:root` defines the full palette: navy/brand (`--navy-900:#0b1623` through
`--brand-50`), gold (`--gold-500:#c89d47` and stops), and the Tailwind slate, emerald,
amber, blue, rose and purple scales it references.

Fonts: **Inter** for text, **JetBrains Mono** for every figure — loaded from Google
Fonts.

Components: app header, KPI cards, allocation and flow tables, priority badges
(`.badge--p1` … `.badge--p6`), balance value states (positive/negative/zero), action
bar, modal, toast, overlay, access gate.

> **For the port: this file is the visual contract.** The class names and tokens must
> survive unchanged.

---

### `StylesReports.html` — 430 lines
**Additions only** — `Styles.html` loads first and owns the tokens. Marked
`RMAS-StylesReports-7G`.

Covers the nav tabs (sticky, deep navy, gold underline on active, monospace count
pills), filter bars, history tables, dashboard KPI strip, chart cards
(`.chart-card`, `.chart-card--full`, `.chart-card__head/__title/__subtitle/__body`) and
every SVG text class the chart engine emits — `.chart-axis-text`, `.chart-bar-text`,
`.chart-point-text`, `.chart-value-text`, `.chart-grid-line`, `.chart-baseline`.

---

### `StylesAudit.html` — 229 lines
**Additions only** — loads third. Action badges colour-coded per audit action
(`--save` green, `--revise` gold, `--blocked` amber, `--failed` / `--unauth` red),
status dots, audit ID styling, detail panels, reason blocks, and the snapshot-diff
tables.

---

## Cross-cutting notes for the port

**Response envelope.** Every public server function returns
`{ok, code, message, data}` via `response_()`. Errors never carry a stack trace to the
browser.

**Naming.** `alloted` is spelled with one `l` throughout. Keep it — renaming breaks
comparison against historical data.

**Three independent client modules.** `Scripts.html`, `Reports.html` and `Audit.html`
share no state; each is a self-contained IIFE binding to IDs in `Index.html`. They map
cleanly onto three frontend route modules.

**Style load order is load-bearing.** `Styles` → `StylesReports` → `StylesAudit`. The
second and third assume the first has already defined the tokens.


---

## Open questions

This build carries several unresolved inconsistencies — a duplicated
`checkInstalledFiles()` across two files, disagreeing build markers, an ambiguous
allocation sector count, and a mislabelled dashboard chart.

They are recorded in `CLAUDE.md`, section 6, under *Known legacy inconsistencies*,
which is the canonical list. They are deliberately not repeated here, so that
resolving one means editing a single file.
