# Build Prompt — Metal Flow History Page

Paste the section below into a chat with the RMAS source attached. Everything was
read out of the current build; nothing is inferred.

**Note before you read it:** this page has **no data table and no pager**. Unlike
Allocation History, it is chart-only. The backend still paginates and returns
`rows` and `page`, but the frontend ignores both. That is deliberate, and the
prompt says so explicitly.

---

## PROMPT

> Build the **Metal Flow History** page for the Royal Metal Allocation System,
> ported from Google Apps Script to Python (FastAPI) + JavaScript. **The UI and
> CSS must be visually identical to the current build** — reuse the existing class
> names and markup structure rather than rebuilding them.
>
> This page is read-only. It never writes.
>
> Metal Flow tracks **supply** — metal acquired — as opposed to Allocation
> History, which tracks demand. Its sector list is a different and smaller set
> (8 flow sectors versus the allocation sectors) and the two must never be merged.
>
> ---
>
> ### Source files that define this page
>
> **Backend (`.gs`)**
>
> | File | What it contributes |
> |---|---|
> | `ReportService.gs` | `getMetalFlowHistory(filters)` — the only endpoint this page calls. Private builders `buildFlowSeries_()`, `buildFlowHeatmap_()`, `limitFlowToWindow_()`, `matchesFlowFilters_()`, `buildFlowOrderMap_()`, `normalizeFilters_()`, `paginate_()`, `shortDateLabel_()`. Constants `HEATMAP_WINDOW_DAYS = 30` and `REPORT_CONFIG.MAX_HEATMAP_DATES = 180`. |
> | `StagingService.gs` | `getUserScope_()`, `filterFlowRowsByScope_()`, `scopeAllowsFlow_()`, `buildSectorPartyMaps_()` — flow scope is resolved via `OPERATOR_FLOW_SECTORS`, falling back to the sector's party. |
> | `DataService.gs` | `readFlowMasterRows_()`, `readFlowSectorDefinitions_()`, `invalidateDataCache_()`. |
> | `AuditService.gs` | `getActiveUserEmail_()`, `isAdministrator_()`. |
> | `DateService.gs` | `toDateKey_()`, `formatDisplayDate_()`, `shiftDateKey_()` — the last is what rolls the heatmap window back from the newest matched date. |
> | `ValidationService.gs` | `response_()`, `round3_()`, `normalizeSectorKey_()`, `handleServerError_()`. |
> | `Config.gs` | `FLOW_LABELS` (Date, Party, Sector, Acquired), flow sector range, `OPERATOR_FLOW_SECTORS`. |
>
> **Frontend (`.html`)**
>
> | File | What it contributes |
> |---|---|
> | `Index.html` | Markup for `<section id="view-flowHistory">` (lines 393–528). Element IDs are the binding contract. |
> | `Reports.html` | `flowFilters()`, `loadFlowHistory()`, `renderFlowHistory()`, `renderFlowHeatmap()`, `sectorShareChart()`, `renderCycleDelta()`, `heatColor()`, `flowColor()`, `niceMax()`, `emptyChart()`, `fmt3()`, `fmtPct()`, `esc()`, CSV export. |
> | `Styles.html` | Tokens, fonts, `.card`, `.btn`, `.input`, `.select`, `.chip`. Loads first. |
> | `StylesReports.html` | `.filter-bar`, `.summary-strip`, `.summary-stat`, `.chart-grid`, `.chart-card`, `.chart-card--full`, `.heat-scroll`, `.heat-legend`, `.heat-note`, and the SVG text classes `.chart-sector-text`, `.chart-value-text`. Loads second. |
>
> ---
>
> ### Page structure — three stacked blocks
>
> #### 1. Filter & Query Controls
>
> A `.card.filter-bar`, same shell as Allocation History but a different hint:
> *"Refine Metal Flow records across dates and parties"*. Applied count in
> `#mfFilterCount`.
>
> | Control | ID | Behaviour |
> |---|---|---|
> | From Date | `mfFrom` | `<input type="date">` |
> | To Date | `mfTo` | `<input type="date">`. Reversed range is **swapped** server-side, not rejected. |
> | Quick Range | `mfQuickRange` | Two buttons only: **7 d** and **30 d**. 7 d active by default. |
> | Metal Flow Sector | `mfSector` | Single select, `"All sectors"` default. Scope-filtered. |
> | Reset | `mfReset` | Clears to defaults, reloads. |
> | Apply Filters | `mfApply` | `.btn--primary` with tick glyph. |
>
> **This page has one dropdown, not two.** `flowFilters()` hard-codes
> `status: 'all'` and `search: ''` with the comments *"the Acquired Status filter
> was removed"* and *"the Search field was removed"*. Keep the backend parameters;
> **do not surface either control.**
>
> #### 2. KPI summary strip — six cards
>
> A `.summary-strip` of six `.summary-stat` cards. Figures use `fmt3()` (three
> decimals, monospace). Note the sources differ: three come from
> `data.summary`, two from `data.heatmap`, one from `data.series`.
>
> | # | Card | Value ID | Sub-line | Source |
> |---|---|---|---|---|
> | 1 | **Records** (navy) | `mfStatRecords` | `mfStatDates` → `"N dates"` | `summary.recordCount`, `summary.dateCount` |
> | 2 | **Total Acquired** (green, emerald dot) | `mfStatTotal` | `mfStatTotalSub` → cycle delta | `summary.totalAcquired`, `summary.cycle` |
> | 3 | **Highest Single Day** | `mfHeatPeak` | `mfHeatPeakSub` → `"<sector> · <full date>"` | `heatmap.peak` |
> | 4 | **Most Active Party** (text value) | `mfHeatTop` | `mfHeatTopSub` → `"N.NNN kg · N.N%"` | `heatmap.mostActive` |
> | 5 | **Average per Day** | `mfStatAvg` | `kg` | `summary.averagePerDay` |
> | 6 | **Sectors Covered** | `mfStatSectors` | `"of 8"` | `summary.sectorCount` |
>
> **Average per day** is `totalAcquired / dateCount` — divided by the number of
> **dates that have records**, not by calendar days in the range. Returns 0 when
> `dateCount` is 0.
>
> **Highest Single Day** is the largest value in any single **cell** — one party
> on one date — not the largest day total. The heatmap separately computes
> `busiestDay` (the highest day *total*); it is returned but not displayed.
>
> **Cycle delta** (`renderCycleDelta`) splits the saved dates in range down the
> middle and compares the newer half against the older:
>
> ```
> change % = (current - previous) / previous * 100
> ```
>
> With an odd number of dates the extra date joins the **current** half, which
> never inflates the change. Return `null` when there are **fewer than 4 dates**,
> or when the older half acquired nothing — a change from zero is undefined, not
> infinite. When null, the sub-line reads *"kg acquired in range"*. Otherwise
> `"↗ +N.N% vs prev N day(s)"` or `"↘ -N.N% …"`, with class
> `summary-stat__sub--up` or `--down`.
>
> #### 3. Charts — a `.chart-grid` of two cards
>
> **There is no table on this page and no pager.** The per-sector table and its
> pager were removed. Everything drawn comes from `data.series` and
> `data.heatmap`, which the server builds from **every matched record**, before
> pagination — so the charts never reflect just one page.
>
> **Chart A — "Daily Acquired Metal by Party"** (`.chart-card--full`, full width)
>
> A Date × Party heatmap, inline SVG, rendered by `renderFlowHeatmap()`.
> Subtitle: *"Daily acquired kilograms by Metal Flow party, for the last 30 days
> of the selected range. Darker cells indicate higher acquisition."*
>
> - Window: the most recent **30 days** (`HEATMAP_WINDOW_DAYS`) counted back from
>   the **newest matched date**, not from today. `limitFlowToWindow_()` does this
>   before the heatmap is built.
> - Hard cap of **180 date columns** (`MAX_HEATMAP_DATES`); when exceeded, keep
>   the most recent and set `truncated`, surfacing `truncationNote` in
>   `#mfHeatNote`.
> - **Parties with zero total across the range are dropped**, so the grid carries
>   no rows of solid zeroes.
> - Rows sort by total acquired descending, then by name.
> - Duplicate records for the same (date, party) are **summed**, not overwritten.
> - Colour: `heatColor(t)` interpolates a sequential blue ramp over
>   `HEAT_STOPS`, where `t = acquired / maximumAcquired` clamped to 1. Zero
>   renders as `rgb(242,244,247)`, not as the ramp's lightest stop.
> - Scroll container `#mfHeatScroll` is focusable (`tabindex="0"`) with an
>   `aria-describedby` pointing at a visually-hidden description.
> - Legend `#mfHeatLegend`: caption *"Acquired (kg)"*, a gradient scale, ticks
>   `0 kg / Low / Medium / <max>` where the last is `#mfHeatLegendMax`.
> - Chip `#mfHeatChip` summarises the grid.
>
> **Chart B — "Total Acquired by Sector"** (half width)
>
> A horizontal bar chart, inline SVG, rendered by `sectorShareChart()`.
>
> - Geometry: `W = 560`, `rowH = 30`, `padL = 118`, `padR = 132`, `padT = 8`;
>   height derived from row count. Bars are 14 px tall with `rx="3"`.
> - Axis maximum via `niceMax(rows[0].total)` — the largest sector's total.
> - Sector names longer than 16 characters truncate to 15 plus an ellipsis, with
>   the full name in a `<title>`.
> - Right-hand label: `"N.NNN · N.N%"` — weight and share of the range total.
> - Bar fill: `flowColor(i)` cycling `FLOW_COLORS`.
> - Two chips on the head: `#mfShareChip` → `"N.NNN kg total"`, `#mfRowChip` →
>   `"N records"`.
> - Empty state via `emptyChart()`: *"No acquired metal recorded in the selected
>   range."*
>
> Both charts drop sectors whose total is zero — `buildFlowSeries_()` applies the
> same rule, since a flat zero line would only crowd the legend.
>
> ---
>
> ### Endpoint contract
>
> `GET /api/metal-flow-history`
>
> Request: `fromDate`, `toDate`, `sectors[]`, `status`, `search`, `limit`,
> `offset`.
>
> Response envelope `{ok, code, message, data}` where `data` holds:
>
> - `rows[]` — `dateKey`, `dateDisplay`, `sector`, `acquired`. *(Returned but
>   unused by the UI; keep for CSV export and API parity.)*
> - `summary` — `recordCount`, `returnedCount`, `truncated`, `dateCount`,
>   `sectorCount`, `totalAcquired`, `averagePerDay`, `cycle{previousAcquired,
>   currentAcquired, dayCount, changePercent}`
> - `series` — `dates[]`, `displays[]`, `sectors[{sector, total, percent,
>   values[]}]`, `grandTotal`
> - `heatmap` — `ok`, `dates[{dateKey, dateLabel, fullDateLabel}]`, `sectors[]`,
>   `cells[{dateKey, dateLabel, fullDateLabel, sector, acquired}]`,
>   `maximumAcquired`, `recordCount`, `totalAcquired`, `dateCount`, `partyCount`,
>   `peak{acquired, sector, dateLabel, fullDateLabel}`, `busiestDay`,
>   `mostActive{sector, total, percent}`, `truncated`, `windowDays`,
>   `truncationNote`
> - `page`, `appliedFilters`
>
> Sort for `rows`: date descending, then flow sector order map, then name.
> Missing sectors sort to 999.
>
> ---
>
> ### Rules that must hold
>
> 1. **Flow scope is applied on the server before any client filter.** Resolve via
>    `OPERATOR_FLOW_SECTORS`; when an operator is absent from that map, fall back
>    to the party owning the flow sector. Administrators see every flow sector.
>    Non-admin with no party → code `NO_PARTY_ASSIGNED`, message *"No party is
>    assigned to your account. Contact the administrator."*
> 2. **Charts are built from all matched records, never from the current page.**
> 3. **Weights are exact.** Integer grams in storage, `Decimal` at the boundary,
>    never `float`. Display three decimals.
> 4. The heatmap window counts back from the **newest matched date**, not today.
> 5. Zero-total sectors are excluded from both charts.
> 6. Duplicate (date, sector) records are summed.
> 7. Cycle change is `null` below four dates or when the older half is zero.
> 8. Do not reintroduce the removed Acquired Status filter or Search box.
> 9. Do not add a data table or pager to this page.

---

## Notes for you, not part of the prompt

**The backend still paginates a page nobody renders.** `getMetalFlowHistory()`
calls `paginate_()`, slices `rows` to 100, and returns a full `page` object. The
frontend stores `R.offset.flowHistory` and sends it, but never renders a pager.
So `rows` is a 100-record slice that only the CSV export touches. Worth deciding
whether the port keeps `rows` at all, or returns the full matched set for export.

**`busiestDay` is computed and returned but never displayed.** The heatmap builder
works out the highest day *total*, while the KPI card shows `peak` — the highest
single *cell*. Both are in the payload. If "Highest Single Day" was meant to be
the day total, the card is bound to the wrong field; if it was meant to be the
single largest acquisition, the label is slightly misleading. Your call.

**`summary.truncated` is hard-coded `false` here too**, exactly as in Allocation
History. The heatmap has its own independent `truncated` flag, which *is* wired
correctly to `#mfHeatNote`.
