# Session: Analysis Dashboard to spec, and live filters everywhere

Date: 2026-09-20

Goal:

1. Build the Analysis Dashboard to `PROMPT_analysis_dashboard.md` — same plots,
   charts and UI as the .md describes.
2. Increase the font size on "Daily Acquired Metal by Party".
3. Remove Apply Filters from every module; sector and date changes apply on the fly.
4. Rework the Filter & Query Controls card so the date pair, Quick Range, Sector
   and Balance Status have space between them.
5. Remove the subtitle "· Refine ledger records across dates, sectors and balance status".

## Decisions taken with the user

| Question | Answer |
|---|---|
| Remove the filter subtitle from one card or all three? | **All three** — this overrides the hint text `PROMPT_analysis_dashboard.md` specifies for the dashboard. |
| `#dbPrint` "Print executive briefing" (dead button in legacy) — wire or drop? | **Drop.** |

## What happened

### The filter card was styled against classes it never used

The real cause of the cramped card. `reports.css` defines a full twelve-column
toolbar — `.filter-bar__grid`, `.filter-group--dates`, `.filter-arrow`,
`.filter-field--range`, `.filter-group--selects`, `.filter-group--selects-3`,
`.filter-actions` — and `filterBar.js` used none of it, reaching for
`.control-bar__field` instead. That class is real, but it belongs to
`tokens.css`'s flex `.control-bar` (the Daily Allocation date strip). Dropped
into a grid it contributes a bare `min-width` and no column span, so the
controls ran together.

Rewritten against the stylesheet's own vocabulary. `audit.js` had the same
problem and the same fix. `.filter-bar__head` was also inverted — `__title` is
the flex wrapper and `__heading` the uppercase text, and the two were swapped.

Apply Filters removed from `filterBar.js` and from `audit.js` (which has its own
bar). Every control now routes through one `apply()` that updates the active
filter count and reloads. `change`, not `input`, so typing a year does not fire
a request for the year 0002 on the way. Audit gained a Reset for parity.

With Apply gone the action column holds Reset alone, so `app.css` gives the
freed width to the selects and opens the grid gap to 16/20px.

### Heatmap type (item 2)

`reports.css` sets the cells at 9.5px. Raised in `app.css` to 11.5px for cells
and column labels, 13px for row labels, and the SVG cell geometry in
`flowHistory.js` was enlarged to match (46×30 from 34×26) — the two have to move
together or the figures overflow their cells.

### Analysis Dashboard

**Backend**

- `cycle_delta()` moved into `services/report_service.py` and now shared by the
  dashboard and Metal Flow History. **This is a behaviour change**: the
  dashboard previously compared the range against the *preceding calendar
  window* (a second query). The spec says split the range's own saved dates down
  the middle, so a range with no earlier data still gets a comparison.
  `_previous_window()` and the `previous_cycle_*` response fields are gone —
  `cycle` carries it all.
- `MAX_TREND_POINTS = 120` cap on `by_date`; `TOP_SECTOR_LIMIT = 10`.
- `latest_balance_by_sector()` — each sector's balance on **its own** latest
  saved date, via a correlated max-date subquery, summed across parties. Drives
  `top_pending`, filtered to `> 0` and capped at 10.
- **The cross-ledger sector rule.** The dashboard now takes a sector filter. An
  allocation-sector filter is applied to demand unconditionally, but to supply
  *only when that sector name also exists in the flow ledger*, matched on the
  normalised name (the ids come from different tables). Otherwise a demand-side
  filter would blank the acquired series and the page would claim no metal
  arrived. `flow_filter_skipped` reports when that happened.
- `NO_PARTY_ASSIGNED` guard, and `is_admin` resolved server-side for the
  operator-only chart.
- `by_sector` now sorts by required descending, so the top-10 chart slices off
  the front.

**Frontend** — `analysis.js` rebuilt to the spec's five cards: Acquired vs
Alloted (A), Closing Balance Trend (B), the operator-only Your Metal Flow Trend
(C, `is_admin === false`, strict), Requirement vs Balance by Sector (D), and Top
Sectors by Pending Balance (E — a table, not a chart). Plus the `.dash-footer`.
The old "Outstanding Balance by Priority" card is gone: the spec returns
`byPriority` but renders it nowhere.

`charts.js` rewritten to the spec's geometry — `groupedBarChart` at
`W=1000 H=300 padL=60 padT=52` with the `rmasBarA`/`rmasBarB` gradients,
`lineChart` at `W=1000 H=260` with a negative-capable Y axis, `sectorBarChart`
at `W=560 rowH=40 padL=132 padR=74` with two bars per row. Axis ticks drop to
whole kilograms above 4 kg, as legacy does.

The markup uses the ids the stylesheet already targets — `#dbChartAcquiredAlloted`,
`#dbChartBalance`, `#dbChartSector`, `#dbPendingTable` with its four column
classes — found by grepping the stylesheet first rather than inventing names.

## Errors / issues encountered

1. **Nearly shipped an `AttributeError`.** After trimming the duplicated
   `previous_cycle_*` fields, one of four patch targets did not match and the
   router was left reading `summary.previous_cycle_acquired_g`, which no longer
   existed. `pytest` stayed green — **no test calls the dashboard endpoint** —
   and only calling the endpoint directly against the real database caught it.
   The patch script printing `SKIP … found 0` is what flagged it; a silent
   `str.replace` would have hidden it.
2. `CycleDelta` was defined *below* `DashboardResponse` after the rename, so the
   annotation could not resolve. Moved above.
3. Wrote a comment claiming `.control-bar__field` "matched no rule at all".
   False — it exists in `tokens.css` under a different parent. Corrected rather
   than left standing.
4. Test fixture missed `saved_by` (NOT NULL) and passed `UserScope` the wrong
   arguments — `flow_sector_ids=[]` where `None` is the correct "fall back to
   party" value. An empty set means something different.

## Achievements

- All five requested items done.
- 169 tests pass (was 165). New: `tests/test_dashboard_rules.py` — four cases
  pinning the cross-ledger rule (including the one that matters: an
  allocation-only sector must *not* blank acquired) and the latest-date-not-a-sum
  rule. `tests/test_flow_cycle.py` became `tests/test_cycle_delta.py` now that
  the helper is shared.
- Verified against the real database for 01–20 Sep: 17 saved days, 846.972 kg
  acquired, utilisation 101.9% (over-allocation is permitted), fulfilment 93.5%,
  cycle +15.3%, 10 pending sectors each dated to its own latest save.
- Every `d.<field>` the dashboard view reads was checked against the live
  payload, and every `$('id')` against its own markup.
- All 17 frontend modules pass `node --input-type=module --check`.
- No browser automation used.

## Future things to implement / open questions

- ~~`frontend/src/views/history.js` is still unreferenced.~~ **Deleted this
  session on the user's confirmation.** It held the first combined
  Allocation-History-and-Metal-Flow-History view, superseded when the two were
  built out separately to their own page specs. Its sole export,
  `renderHistoryView`, was imported nowhere. All 16 remaining frontend modules
  still parse and every import target resolves.
- The dashboard endpoint has **no HTTP-level test**. That is exactly the gap
  that hid the AttributeError above. Worth adding one that logs in as an
  operator and asserts `is_admin` is false and scope holds.
- Still unresolved, all flagged, none silently decided:
  - Fulfilment rate is `alloted / (previous + required)` on Allocation History
    and `alloted / required` here. The spec explicitly says keep both.
  - `summary.truncated` is hard-coded `false` in legacy on both history pages.
  - A duplicate `request_id` errors (legacy) where CLAUDE.md rule 12 and
    `schema.sql`'s `response_json` describe replaying the original result.
  - The revise path has no idempotency guard.
  - `byPriority` is still computed and returned but rendered nowhere — the spec
    asks whether to keep paying for it. Left in for API parity.
