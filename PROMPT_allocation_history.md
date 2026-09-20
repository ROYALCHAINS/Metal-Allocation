# Build Prompt — Allocation History Page

Paste the section below into a chat with the RMAS source attached. Everything in
it was read out of the current build; nothing is inferred.

---

## PROMPT

> Build the **Allocation History** page for the Royal Metal Allocation System,
> ported from Google Apps Script to Python (FastAPI) + JavaScript. **The UI and
> CSS must be visually identical to the current build** — reuse the existing class
> names and markup structure rather than rebuilding them.
>
> This page is read-only. It never writes.
>
> ---
>
> ### Source files that define this page
>
> **Backend (`.gs`)**
>
> | File | What it contributes |
> |---|---|
> | `ReportService.gs` | `getAllocationHistory(filters)` — the only endpoint this page calls. Also `getHistoryFilterOptions()` for dropdown values, and the private helpers `normalizeFilters_()`, `matchesAllocationFilters_()`, `paginate_()`, `inDateWindow_()`, `buildSectorOrderMap_()`. `REPORT_CONFIG` holds the limits. |
> | `StagingService.gs` | `getUserScope_()`, `filterRowsByScope_()`, `buildSectorPartyMaps_()` — party scoping, applied server-side before any client filter. |
> | `DataService.gs` | `readMasterRows_()` — reads Metal Master; `invalidateDataCache_()`. |
> | `AuditService.gs` | `getActiveUserEmail_()`, `isAdministrator_()` — identity behind the scope check. |
> | `DateService.gs` | `toDateKey_()`, `isValidDateKey_()`, `formatDisplayDate_()` — produces the `'Mon, 17-Aug-2026'` display form. |
> | `ValidationService.gs` | `response_()` envelope, `round3_()`, `normalizeSectorKey_()`, `handleServerError_()`. |
> | `Config.gs` | `MASTER_LABELS`, sector definitions, `DECIMALS: 3`. |
>
> **Frontend (`.html`)**
>
> | File | What it contributes |
> |---|---|
> | `Index.html` | Markup for `<section id="view-allocationHistory">` (lines 252–392). All element IDs are the binding contract. |
> | `Reports.html` | `allocationFilters()`, `loadAllocationHistory()`, `renderAllocationHistory()`, `renderPager()`, `updateFilterCount()`, `fmt3()`, `fmtPct()`, `esc()`, CSV export. |
> | `Styles.html` | Design tokens, fonts, `.card`, `.btn`, `.input`, `.select`, `.chip`. Loads first. |
> | `StylesReports.html` | `.filter-bar`, `.summary-strip`, `.summary-stat`, `.history-table`, `.pager`, `.pill-pending` / `.pill-cleared`, `.empty-state`, `.truncation-note`. Loads second. |
>
> ---
>
> ### Page structure — three stacked blocks
>
> #### 1. Filter & Query Controls
>
> A `.card.filter-bar`. Header reads **"Filter & Query Controls"** with a funnel
> icon, the hint *"Refine ledger records across dates, sectors and balance
> status"*, and an applied-count readout on the right (`#ahFilterCount`) showing
> `"No filters active"` or `"N filters active"`.
>
> Controls, left to right:
>
> | Control | ID | Behaviour |
> |---|---|---|
> | From Date | `ahFrom` | `<input type="date">`. Blank = default look-back. |
> | To Date | `ahTo` | `<input type="date">`. If from > to, the server **swaps them** rather than erroring. |
> | Quick Range | `ahQuickRange` | Two buttons only: **7 d** and **30 d**. `data-days`. 7 d is active by default. Sets the two date inputs. |
> | Sector | `ahSector` | Single select, `"All sectors"` default. Populated from `getHistoryFilterOptions()` — **only sectors the user's scope allows**. |
> | Balance Status | `ahStatus` | Five options: `all`, `pending` (balance > 0), `cleared` (balance ≤ 0), `allocated` (alloted > 0), `unallocated` (alloted = 0). |
> | Reset | `ahReset` | Clears to defaults and reloads. |
> | Apply Filters | `ahApply` | `.btn--primary` with a tick glyph. Triggers the fetch. |
>
> **Do not add a Purity filter or a Search box.** The backend still accepts
> `purities` and `search`, and `allocationFilters()` in `Reports.html` hard-codes
> them to `'all'` and `''` with the comments *"the Purity filter was removed"* and
> *"the Search field was removed"*. These were deliberately removed from the UI.
> Keep the backend parameters; leave them unexposed.
>
> #### 2. KPI summary strip
>
> A `.summary-strip` of five `.summary-stat` cards, all fed from
> `response.data.summary`. Figures use `fmt3()` — three decimals, monospace.
>
> | # | Card | Value ID | Sub-line | Computed as |
> |---|---|---|---|---|
> | 1 | **Records** (navy) | `ahStatRecords` | `ahStatDates` → `"N dates · M sectors"` | count of matched rows; distinct date and sector keys |
> | 2 | **Previous Requirement** | `ahStatPrev` | `kg` | sum of `previousRequirement` |
> | 3 | **Today's Required** | `ahStatRequired` | `kg` | sum of `todayRequired` |
> | 4 | **Total Alloted** (green) | `ahStatAlloted` | `ahStatFulfil` → `"N.N% fulfilment rate"` | sum of `alloted`; rate below |
> | 5 | **Total Balance** (closing) | `ahStatBalance` | `ahStatPeak` → `"Trajectory peak: N.NNN kg on <date>"` | sum of `balance`; peak below |
>
> Card 5 carries a **"Latest"** badge; card 4 a navy status dot.
>
> **Fulfilment rate** — this exact definition, from `ReportService.gs`:
>
> ```
> demand     = previousRequirement + todayRequired
> fulfilment = alloted / demand * 100
> ```
>
> Because `balance = demand − alloted`, this is equivalently
> `(1 − balance / demand)`. **When demand ≤ 0, report 0, not a large number.** A
> negative `previousRequirement` means the sector was over-allocated earlier and
> is carrying credit, which can drive demand to or below zero.
>
> **Trajectory peak** — the highest *total closing balance* reached on any single
> date in range, with that date. Group matched rows by date, sum `balance` per
> date, take the maximum. Computed from rows already fetched — do not issue a
> second query.
>
> #### 3. Allocation History table
>
> A `.card.panel` headed **"Allocation History"** with a `.chip` showing
> `"N rows"` (`#ahRowChip`).
>
> Eight columns, in this order. The four numeric ones carry `class="num"` and
> every cell carries a `data-label` attribute for the responsive stacked layout:
>
> | Column | Source field | Format |
> |---|---|---|
> | Date | `dateDisplay` | `'Mon, 17-Aug-2026'`, `.date-cell` |
> | Sector | `sector` | text |
> | Purity | `purity` | text, verbatim |
> | Prev. Requirement | `previousRequirement` | `fmt3` |
> | Today's Required | `todayRequired` | `fmt3` |
> | Alloted | `alloted` | `fmt3` |
> | Balance | `balance` | `fmt3` |
> | Status | *derived* | pill |
>
> **Status is derived on the client**, not stored: `balance > 0` renders
> `<span class="pill-pending">Pending</span>`, otherwise
> `<span class="pill-cleared">Cleared</span>`.
>
> The payload also carries `priority` per row. It drives **sort order only** and
> is **not displayed as a column** — keep it in the response, keep it out of the
> table.
>
> **Sort:** date descending (newest first), then by the sector order map, then
> sector name. Sectors missing from the order map sort to position 999.
>
> **Empty state:** `#ahEmpty` — *"No records found"* / *"Adjust the date range or
> filters and apply again."* Hide the table when there are no rows.
>
> **Pagination:** `.pager` with `ahPrev` / `ahNext` and `ahPageInfo`. Page size
> 100 (`REPORT_CONFIG.PAGE_SIZE`), hard ceiling 3000 rows
> (`MAX_ROWS_RETURNED`), default look-back 30 days (`DEFAULT_RANGE_DAYS`). The
> server returns `page: {currentPage, totalPages, pageSize, offset, totalRecords,
> firstRecord, lastRecord, hasPrevious, hasNext}`.
>
> **Truncation note:** `#ahTruncated`, shown only when `summary.truncated` is
> true.
>
> ---
>
> ### Endpoint contract
>
> `GET /api/allocation-history`
>
> Request: `fromDate`, `toDate`, `sectors[]`, `purities[]`, `status`, `search`,
> `limit`, `offset`.
>
> Response follows the standard envelope `{ok, code, message, data}` with
> `data = {rows[], summary{}, page{}, appliedFilters{}}`.
>
> Row: `dateKey`, `dateDisplay`, `priority`, `sector`, `purity`,
> `previousRequirement`, `todayRequired`, `alloted`, `balance`.
>
> Summary: `recordCount`, `returnedCount`, `truncated`, `dateCount`,
> `sectorCount`, `totals{}`, `peakBalance{value, dateDisplay}`, `totalDemand`,
> `fulfilmentRate`.
>
> ---
>
> ### Rules that must hold
>
> 1. **Party scope is applied on the server before any client filter.** An
>    operator must not be able to widen scope from the browser. If a non-admin has
>    no party assigned, return code `NO_PARTY_ASSIGNED` with the message *"No
>    party is assigned to your account. Contact the administrator."*
> 2. **Sector dropdown values are scope-filtered too** — never return a sector the
>    user may not see.
> 3. **Weights are exact.** Store as integer grams; convert to `Decimal` at the
>    boundary. Never `float`. Display three decimals via `fmt3`.
> 4. Invalid dates are **dropped, not rejected**; reversed ranges are **swapped**.
> 5. `limit` outside `1..3000` falls back to 100. Negative `offset` becomes 0.
> 6. Errors return a safe message; the stack goes to the server log only.
> 7. Keep the spelling **`alloted`** (one `l`) in every field name.
> 8. Do not reintroduce the removed Purity filter or Search box.

---

## Notes for you, not part of the prompt

Two things surfaced while reading the source that you may want to decide on:

**The backend supports more filtering than the UI exposes.** `normalizeFilters_()`
handles `purities`, `priorities` and a free-text `search` across sector, priority
and purity. The page sends `purities: 'all'`, `search: ''` and never sends
`priorities` at all. The capability is live and tested — if you ever want those
filters back, it's a frontend-only change.

**`summary.truncated` is hard-coded to `false`.** The field is returned, the
frontend checks it, and `#ahTruncated` is wired up — but `getAllocationHistory()`
always sets it false, so the note can never appear. Either the pagination made it
redundant, or the flag was never connected to `MAX_ROWS_RETURNED`. Worth deciding
before the port, since the UI element exists either way.
