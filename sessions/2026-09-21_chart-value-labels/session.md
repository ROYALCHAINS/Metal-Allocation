# Session: On-plot value labels for the dashboard charts

Date: 2026-09-21

Goal: Print the figures on the Analysis Dashboard's two headline charts — a label above each
bar in "Acquired vs Alloted by Date", and above each point in "Closing Balance Trend" — as
whole numbers rather than the system's usual three decimals. Reference screenshots supplied:
`Acquired vs Alloted by Date.png` and `Closing Balance Trend.png`.

## What happened

### It turned out to be a port, twice over

Both screenshots are of the **legacy** app, not the port — the Closing Balance subtitle still
reads *"Cumulative physical vault stock position"*, wording the port deliberately changed. So
legacy already draws exactly these labels, in `Reports.html`: rotated bar labels at `:507-520`
and horizontal point labels at `:593-595`.

And the CSS was already here. `frontend/src/styles/reports.css:295-297`:

```css
/* Figures printed on the plot itself, so values read without hovering. */
.chart-bar-text{font-family:var(--mono);font-size:8.5px;fill:var(--slate-500);font-weight:600;}
.chart-point-text{font-family:var(--mono);font-size:9.5px;fill:var(--slate-700);font-weight:700;}
```

Both shipped, both referenced nowhere — except `charts.js:8-9`, whose header comment already
*claimed* the engine emitted them. It didn't. This change makes that claim true. Same pattern
as `.revision-note` last session: CSS written ahead of the markup. **No CSS was added.**

### The geometry trap

Legacy's x-coordinates do **not** transfer, because the two implementations lay the bar pair
out differently:

| | rect x | width | rect centre |
|---|---|---|---|
| legacy bar A | `cx - barW - 1` | `barW` | `cx - barW/2 - 1` |
| legacy bar B | `cx + 1` | `barW` | `cx + barW/2 + 1` |
| port | `centre - barW + j*barW` | `barW - 1` | `centre + (j - 0.5)*barW - 0.5` |

Copying legacy verbatim would put bar A's label 0.5px left and bar B's 1.5px right of centre
— 11% of a bar at `barW = 13`, and **37% at `barW = 4`**, where bar B's label would sit over
the gap instead of the bar. Invisible in code review; wrong in every render.

Fixed structurally rather than by hand-writing two constants: the rect's own geometry is
hoisted into `x` / `w` / `y` locals, so the label reads as *"the centre of the rect I just
drew"* and the mistake cannot recur. **Verified the refactor is inert** by diffing the emitted
`<rect>` markup against `HEAD` — byte-identical.

### Implementation

- **`frontend/src/lib/format.js`** — new exported `formatPlotKg(grams)` plus a private
  `trimZeros`. Ports legacy's `fmt0`, tiered by magnitude: ≥10 kg whole, ≥1 kg one decimal
  trimmed, <1 kg three decimals trimmed, zero as `"0"`. It belongs in this file because its
  own header quotes the rule *"All money/weight formatting goes through one helper in
  src/lib/."* Takes integer grams (legacy took float kg). The bottom tier reuses the existing
  `formatGrams()`, so a label can never disagree with its own tooltip.
- **`frontend/src/components/charts.js`** — the two emits, plus the import.

Legacy's `round3()` and its sub-half-gram `"-0"` guard were **not** ported: the input is
already an integer number of grams, so there is nothing to round away and `"-0"` is
unreachable. Noted in the code rather than carried as cargo.

### Three deliberate asymmetries, each commented so nobody "fixes" them

1. **Bar labels are guarded on `h > 0`; point labels are not.** A zero *bar* is an absent bar
   — and two `"0"`s a pixel apart would collide on the baseline over the date tick. A zero
   *point* is a real reading: the balance cleared that day.
2. **`labelEvery` does not apply to value labels.** It exists to thin the horizontal date
   ticks, which genuinely collide (`"02 Sep"` ≈ 40px against a ~30px slot at 31 dates). The
   value labels are rotated precisely so they don't need thinning — legacy's own stated answer
   to crowding. Legacy thins only the ticks.
3. **No `escapeText()` on either label**, unlike every other text emit in the file, because
   `formatPlotKg` returns only `[-0-9.]`.

## Errors / issues encountered

- **The inertness check wouldn't run at first.** Comparing old and new output meant importing
  the `HEAD` copy of `charts.js` from the scratchpad, where its relative `../lib/format.js`
  import doesn't resolve. Rewrote the import in the copy to an absolute `file://` URL.
- No other failures — the geometry was derived before writing, rather than debugged after.

## Achievements

- Both charts labelled, matching the reference screenshots.
- **The formatter's full tier table verified**, 19 cases including the `8800 → "8.8"` that
  appears in the supplied screenshot, plus `9999 → "10"`, `-10500 → "-10"`, `1 → "0.001"`,
  `1250400 → "1250"`, `0 → "0"`. All correct.
- **The geometry trap checked directly** — for 5, 12, 31 and 62 dates, every label's anchor
  recomputed independently from its own `<rect>`: max error **0.05px**, which is the
  `.toFixed(1)` rounding and well under one device pixel. This is the check a visual pass
  cannot make.
- Label counts prove the guards: 8 labels for 10 bars where two were zero; 4 of 4 line points
  labelled including a zero and a negative (`198  0  -4.2  165`).
- Paint order verified — each point label is emitted after its circle and the path, so the
  2px stroke cannot sit on the digits.
- Headroom verified: a full-height bar's label sits at `y = 47`, a top line point's at
  `y = 32`, both inside the viewBox.
- Generated SVG parses clean as XML — the realistic failure mode of string-built markup.
- **Rendered from real database figures**: bars read `45 39 43 38 38 40 52 60 55 61 40 36`
  and the balance line `17 36 43 44 43 45` — whole numbers, as asked.
- `charts.js:8-9`'s long-standing false claim about emitting these classes is now true.
- Backend untouched: **270 tests still passing**.

### Decisions taken this session

1. **Legacy's formatter verbatim**, tiered by magnitude, rather than a flat trim of three
   decimals. It is what produced the screenshots, and it keeps a 350 g balance readable as
   `0.35` instead of collapsing it to `0`.
2. **Every bar labelled, rotated, nothing hidden** at dense ranges.
3. **Labels only** — the other differences between the screenshots and the port stay out.

## Future things to implement / open questions

- **Three legacy features visible in `Closing Balance Trend.png` but absent from the port**,
  flagged so they are never mistaken for something this change broke: the amber gradient
  area-fill under the line (`Reports.html:557-561`, `:581-583`), hollow white nodes with a
  coloured stroke and a larger ringed final node (`:587-591`), and the dark `165 kg` callout
  pill on the last point (`:606-613`) — whose `.chart-callout-text` class **also** already
  ships unused at `reports.css:294`. Legacy's line stroke is 3px against the port's 2px.
  One coherent follow-up ticket.
- **The Flow Trend chart inherited point labels**, since it calls the same `lineChart`
  (`analysis.js:339`). Left deliberately: same chart type, same density, same argument.
  Suppressing it would mean an opt-out parameter for a chart nobody asked to exclude.
- **Line labels will touch at ~60+ dates**, where a 3-char 9.5px label exceeds the step.
  Legacy has the identical limit and does not thin them.
- **No thousands separator** on labels (`1250400 → "1250"`) while the axis beside them uses
  `"1,250"` via the private `wholeKg`. Legacy behaved this way, and a separator costs width
  inside a rotated 8.5px label — but the two do visibly disagree.
- **`wholeKg` is still private in `charts.js:52`** — arguably the same
  formatting-in-the-wrong-place issue this change avoided, but moving it touches the axis,
  the totals strip and the sector chart.
- **No JS test runner exists.** Verified: no `package.json` outside `.metal/`, so CLAUDE.md
  section 5's `cd frontend && npm install` block is stale and describes a toolchain that is
  not present. The checks above were run ad-hoc through Node v24 against the pure modules;
  nothing was added to the repo, because choosing a runner is the user's call.
- **Not seen in a browser.** Real glyph metrics at 30+ dates, that the classes resolve and
  the labels are not invisible, the negative-point-in-a-V collision, and fidelity to the two
  PNGs all still need an eyeball on the running dashboard.
