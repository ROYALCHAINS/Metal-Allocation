# Build Prompt — Analysis Dashboard Page

Paste the section below into a chat with the RMAS source attached. Everything was
read out of the current build; nothing is inferred.

**Two things to know before you read it.** This page has a **role-conditional
chart** — one card appears only for non-admins. And it contains a **known
mislabelled chart**, flagged in the notes at the end.

---

## PROMPT

> Build the **Analysis Dashboard** for the Royal Metal Allocation System, ported
> from Google Apps Script to Python (FastAPI) + JavaScript. **The UI and CSS must
> be visually identical to the current build** — reuse the existing class names and
> markup structure rather than rebuilding them.
>
> This page is read-only. It never writes.
>
> It is the only page that joins **both ledgers**: Metal Master (demand) and Metal
> Flow Master (supply). One endpoint returns everything.
>
> ---
>
> ### Source files that define this page
>
> **Backend (`.gs`)**
>
> | File | What it contributes |
> |---|---|
> | `ReportService.gs` | `getDashboardSummary(filters)` — the single endpoint. Builds five series plus the KPI block. Uses `normalizeFilters_()`, `inDateWindow_()`, `buildFlowHeatmap_()`, `formatDisplayDate_()`. Constants `MAX_TREND_POINTS = 120`, `TOP_SECTOR_LIMIT = 10`. |
> | `StagingService.gs` | `getUserScope_()`, `filterRowsByScope_()`, `filterFlowRowsByScope_()`, `buildSectorPartyMaps_()` — **both** ledgers are scoped independently. |
> | `DataService.gs` | `readMasterRows_()`, `readFlowMasterRows_()`, `invalidateDataCache_()`. |
> | `AuditService.gs` | `getActiveUserEmail_()`, `isAdministrator_()` — the admin flag drives the conditional chart. |
> | `DateService.gs` | `toDateKey_()`, `formatDisplayDate_()`. |
> | `ValidationService.gs` | `response_()`, `round3_()`, `normalizeSectorKey_()`, `handleServerError_()`. |
> | `Config.gs` | `MASTER_LABELS`, `FLOW_LABELS`, sector definitions, `DECIMALS: 3`. |
>
> **Frontend (`.html`)**
>
> | File | What it contributes |
> |---|---|
> | `Index.html` | Markup for `<section id="view-dashboard">` (lines 529–729). Element IDs are the binding contract. |
> | `Reports.html` | `dashboardFilters()`, `loadDashboard()`, `renderDashboard()`, and the chart engine: `groupedBarChart()`, `lineChart()`, `sectorBarChart()`, `niceMax()`, `emptyChart()`, `shortDate()`, `renderCycleDelta()`, `fmt0()`, `fmt3()`, `fmtPct()`, `esc()`. |
> | `Styles.html` | Tokens, fonts, `.card`, `.btn`, `.input`, `.select`, `.chip`. Loads first. |
> | `StylesReports.html` | `.filter-bar`, `.summary-strip`, `.summary-stat`, `.chart-grid`, `.chart-card`, `.chart-card--full`, `.chart-legend`, `.legend-swatch`, `.dash-footer`, `.history-table`, and the SVG text classes `.chart-axis-text`, `.chart-bar-text`, `.chart-point-text`, `.chart-value-text`, `.chart-sector-text`, `.chart-grid-line`, `.chart-baseline`. Loads second. |
>
> **There is no charting library.** All charts are hand-written inline SVG. Do not
> substitute Chart.js, Recharts, D3 or anything else — it would change the
> appearance.
>
> ---
>
> ### Page structure — four stacked blocks
>
> #### 1. Filter & Query Controls
>
> A `.card.filter-bar`. Hint: *"Refine the analysis horizon across dates and
> sectors"*. Applied count in `#dbFilterCount`.
>
> | Control | ID | Behaviour |
> |---|---|---|
> | From Date | `dbFrom` | `<input type="date">` |
> | To Date | `dbTo` | `<input type="date">`. Reversed range is swapped server-side. |
> | Quick Range | `dbQuickRange` | Two buttons: **7 d**, **30 d**. 7 d active by default. |
> | Sector | `dbSector` | Single select, `"All sectors"`. Scope-filtered. |
> | Reset | `dbReset` | Clears and reloads. |
> | Apply Filters | `dbApply` | `.btn--primary` with tick glyph. |
>
> `dashboardFilters()` sends only `fromDate`, `toDate` and `sectors` — no status,
> no search, no priorities. Keep it that way.
>
> **Critical cross-ledger rule.** Metal Flow has its own sector list, separate from
> the allocation sectors. A sector filter must **not** silently blank the acquired
> series. Apply the sector filter to flow rows **only when the selected key
> actually exists in the flow master**:
>
> ```
> flowKeysPresent = set of sectorKeys in the scoped flow rows
> flowFilterActive = any selected sector key is in flowKeysPresent
> → filter flow rows by sector only when flowFilterActive
> ```
>
> Allocation rows are filtered by sector unconditionally.
>
> #### 2. KPI summary strip — six cards
>
> All from `data.kpis`. Figures use `fmt3()`; percentages `fmtPct()`.
>
> | # | Card | Value ID | Sub-line | Computed as |
> |---|---|---|---|---|
> | 1 | **Saved Days** (navy) | `dbStatDays` | `dbStatLatest` → latest date, or `"no data"` | `byDate.length` |
> | 2 | **Total Acquired** (green, emerald dot) | `dbStatAcquired` | `dbStatAcquiredDelta` → cycle delta | sum of `acquired` across `byDate` |
> | 3 | **Total Alloted** (navy dot) | `dbStatAlloted` | `dbStatFulfil` → `"N.N% fulfilment rate"` | sum of `alloted` |
> | 4 | **Utilisation** | `dbStatUtilisation` | `"alloted vs acquired"` | `totalAlloted / totalAcquired * 100` |
> | 5 | **Avg Daily Acquired** | `dbStatAvg` | `"kg per saved day"` | `totalAcquired / byDate.length` |
> | 6 | **Closing Balance** (closing, "Latest" badge) | `dbStatClosing` | `dbStatPeak` → `"Trajectory peak: N.NNN kg on <date>"` | `balance` of the **last** date in `byDate` |
>
> **Two different ratios — do not conflate them:**
>
> ```
> utilisation     = totalAlloted / totalAcquired * 100   ← supply consumed
> fulfilmentRate  = totalAlloted / totalRequired  * 100   ← demand met
> ```
>
> Both return 0 when their denominator is ≤ 0.
>
> Note `fulfilmentRate` here divides by `totalRequired` (today's required only).
> **This differs from Allocation History**, where the denominator is
> `previousRequirement + todayRequired`. Keep both as they are — they are
> different questions.
>
> **Closing Balance is the last date's balance, not a sum** across the range.
> **Trajectory peak** is the highest single-date total balance, with its date.
>
> **Cycle delta** (`renderCycleDelta`) splits `byDate` down the middle and compares
> the newer half's acquired against the older half's. The extra date on an odd
> count joins the **current** half. Returns `null` below **4 dates** or when the
> older half acquired nothing. When null the sub-line reads *"kg acquired in
> range"*; otherwise `"↗ +N.N% vs prev N day(s)"` with class
> `summary-stat__sub--up` or `--down`.
>
> #### 3. Charts — a `.chart-grid` of five cards
>
> **Chart A — "Acquired vs Alloted by Date"** — full width, `groupedBarChart()`
>
> - Subtitle: *"Comparative inflow versus fulfilment volume over the selected
>   horizon."*
> - Source: `data.byDate` → `{label: dateDisplay, short: shortDate(dateKey),
>   a: acquired, b: alloted}`
> - Colours: acquired `#10b981`, alloted `#1e3a5f`, each a vertical gradient
>   (`rmasBarA`, `rmasBarB` `<linearGradient>` defs).
> - Geometry: `W=1000, H=300, padL=60, padR=20, padT=52, padB=50`.
>   `slot = plotW / rows.length`, `barW = clamp(slot/2.8, 4, 13)`.
> - Axis max via `niceMax()`; `axDec = max >= 4 ? 0 : 1`.
> - X labels drawn every `ceil(rows.length / 10)` to avoid crowding.
> - Chip `#dbChart1Chip` → `"N day(s)"`. Legend below the body.
>
> **Chart B — "Closing Balance Trend"** — full width, `lineChart()`
>
> - Source: `data.byDate` → `{value: balance}`. Colour `#d97706`.
> - Geometry: `W=1000, H=260, padL=60, padR=20, padT=42, padB=50`.
> - Y range: max via `niceMax()`; min is `-niceMax(abs(min))` when any value is
>   negative, else 0. `axDec = span >= 4 ? 0 : 1`.
> - Evenly spaced points; a single point centres in the plot.
> - Chip `#dbChart2Chip` (amber) → `"Latest N.NNN kg"`.
>
> **Chart C — "Your Metal Flow Trend"** — full width, **hidden by default**
>
> - Card `#dbFlowTrendCard` carries the `hidden` class in markup.
> - Shown **only when `R.isAdmin === false`** — that is, for operators, who have
>   no Metal Flow History tab and see their flow trend here instead. Strict
>   equality: an undefined admin flag must leave it hidden.
> - `lineChart()` over `data.byDate` → `{value: acquired}`, colour `#10b981`.
> - Chip `#dbFlowTrendChip` → `"N.NNN kg over N day(s)"`, summing the plotted
>   points client-side.
>
> **Chart D — "Requirement vs Balance by Sector"** — half width,
> `sectorBarChart()`
>
> - Subtitle: *"Comparative outstanding balance against demand volume."*
> - Source: `data.bySector`, already sorted by `required` descending;
>   **the chart takes the top 10**.
> - Geometry: `W=560, rowH=40, padL=132, padR=74, padT=8`. Two bars per row —
>   required `#1e3a5f`, balance `#f59e0b`.
> - Axis max from `required` and `max(0, balance)` via `niceMax()`.
> - Sector names over 20 characters truncate to 19 plus ellipsis, full name in a
>   `<title>`.
>
> **Chart E — "Top Sectors by Pending Balance"** — half width, **a table, not a
> chart**
>
> - Chip: *"Latest saved date per sector"*. Subtitle: *"Live operational ledger
>   ranking, based on the recorded pending requirement."*
> - Columns: `#` (`.col-rank`), `Sector` (`.col-sector-name`, rendered with
>   `.date-cell`), `Pending Balance` (`.num .col-pending`), `As Of`
>   (`.col-asof`).
> - Source: `data.topPending` — **each sector's balance on its own latest saved
>   date**, not a sum over the range. Filtered to `pending > 0`, sorted
>   descending, capped at 10 (`TOP_SECTOR_LIMIT`).
> - Empty state `#dbPendingEmpty`: *"No pending balance"* / *"Every sector is
>   fully cleared for the selected range."* Hide the table when empty.
>
> #### 4. Dashboard footer
>
> `.dash-footer` — status dot, *"Analytics synchronised"*, then:
>
> | Element | Content |
> |---|---|
> | `#dbFootSectors` | `"N sector(s) active"` — `bySector.length` |
> | `#dbFootSynced` | `"Last synced HH:MM"` — **client clock at render time**, not a server timestamp |
> | `#dbFootAcquired` | `"N.NNN kg"` — `kpis.totalAcquired` |
> | `#dbPrint` | *"Print executive briefing"* button |
>
> ---
>
> ### Endpoint contract
>
> `GET /api/dashboard-summary`
>
> Request: `fromDate`, `toDate`, `sectors[]`.
>
> Response envelope `{ok, code, message, data}` where `data` holds:
>
> - `kpis` — `dayCount`, `totalAcquired`, `totalAlloted`, `totalRequired`,
>   `unallocated`, `utilisation`, `averageDailyAcquired`, `latestDate`,
>   `latestDateDisplay`, `latestClosingBalance`, `pendingSectorCount`,
>   `totalPendingLatest`, `fulfilmentRate`, `previousCycleAcquired`,
>   `currentCycleAcquired`, `acquiredChangePercent`, `cycleDayCount`,
>   `peakClosingBalance`, `peakClosingDate`
> - `byDate[]` — `dateKey`, `dateDisplay`, `previousRequirement`, `required`,
>   `alloted`, `balance`, `acquired`, `unallocated`, `utilisation`.
>   **Capped at the most recent 120 points** (`MAX_TREND_POINTS`).
> - `bySector[]` — `sector`, `priority`, `required`, `alloted`, `balance`,
>   `latestBalance`, `latestDate`, `latestDateDisplay`. Sorted by `required` desc.
> - `byPriority[]` — `priority`, `alloted`, `required`, `balance`, `share`.
>   *(Returned but not rendered by any card.)*
> - `topPending[]` — `sector`, `priority`, `pending`, `asOf`
> - `heatmap` — from `buildFlowHeatmap_(flow)`. *(Returned but not rendered on
>   this page.)*
> - `appliedFilters`
>
> The success message is `"Analysis prepared for N saved date(s)."`, or
> `"No saved records matched the selected filters."` when empty.
>
> ---
>
> ### Rules that must hold
>
> 1. **Both ledgers are scope-filtered on the server, independently**, before any
>    client filter. Non-admin with no party → `NO_PARTY_ASSIGNED`, message *"No
>    party is assigned to your account. Contact the administrator."*
> 2. **An allocation-sector filter must not blank the acquired series.** Apply the
>    sector filter to flow rows only when the key exists in the flow master.
> 3. **Utilisation and fulfilment are different ratios** with different
>    denominators. Do not merge them.
> 4. **Closing Balance is the latest date's value, not a range sum.**
> 5. **`topPending` uses each sector's own latest saved date**, not a range total.
> 6. `byDate` is capped at the most recent 120 points.
> 7. **Weights are exact.** Integer grams in storage, `Decimal` at the boundary,
>    never `float`. Three decimals on display.
> 8. The Metal Flow Trend card is shown only when the user is **not** an admin,
>    tested with strict equality against `false`.
> 9. All charts are hand-written SVG. Do not introduce a charting library.

---

## Notes for you, not part of the prompt

**The Closing Balance Trend card is mislabelled.** Its subtitle
(`Index.html` line 652) reads *"Cumulative physical vault stock position,
measured in kilograms"*, but the series plots the summed outstanding `balance` —
outstanding requirement, not vault stock — and it is not cumulative. We agreed
earlier to keep the Balance semantics, so the subtitle is the thing that needs
correcting. The prompt above describes the data accurately and leaves the
subtitle text alone; decide whether the port carries the wrong wording forward.

**Two payload sections are computed and never rendered.** `byPriority` (with its
`share` percentage) and `heatmap` are both built by `getDashboardSummary()` and
returned, but no dashboard card consumes either. `heatmap` duplicates work the
Metal Flow History page already does. Dropping them from this endpoint would cut
real work per request; keeping them costs a little payload. Worth a decision
before the port rather than after.

**`#dbFootSynced` reads the client clock**, not a server timestamp, so it shows
the browser's local time at render. Fine as a freshness cue, misleading if anyone
treats it as a data timestamp.

**`#dbPrint` has no handler in `Reports.html`.** The button renders but does
nothing. Either wire it to `window.print()` with a print stylesheet during the
port, or drop it.
