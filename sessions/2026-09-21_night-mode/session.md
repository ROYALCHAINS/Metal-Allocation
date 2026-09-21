# Session: Night mode

Date: 2026-09-21

Goal: Build a night mode for the app using `RMAS_PORT_LEDGER.html`'s palette and type,
restyle the KPI cards to that page's tile treatment, and add a toggle beside the user name
and role pill.

## What happened

### The ledger turned out to be an implementation, not just a reference

`RMAS_PORT_LEDGER.html:16-89` already declares a semantic alias layer and a three-state
theme contract, and `:150-164` is the tile target. Its palette is this app's own
`tokens.css` palette renamed to roles (`--accent` = `--gold-600`, dark `--surface` =
`--brand-850`). Nothing had to be invented.

### The size of the job, measured before starting

| | |
|---|---|
| Colour tokens that flip from one `:root` override | **59** |
| Hardcoded CSS literals that do **not** flip | **135** (tokens 79, reports 37, audit 19, app **0**) |
| Colour literals in JavaScript | **~27** |
| Pre-existing theme scaffolding | **none** |

### The decision that made it tractable

Inverting eleven neutral tokens plus the three shadows, rather than overriding 135
selectors. `var(--white)` alone has **20 consumers** — verified — **including all five
`!important` mobile card rules**, which no later non-important rule could otherwise beat.
`.card`, `.input`, `.btn`, `.readonly-box`, `.chart-card`, `.pager__btn` and a dozen more
became correct with **zero selectors written**.

The names are documented as denoting **rank, not hue**: `--white` is "the lightest
surface", which in dark mode is `#101e30`. Ordering is preserved, so every rule of the
form `{background:var(--white);color:var(--slate-900)}` keeps correct contrast untouched.

Two tokens were deliberately **not** inverted. `--slate-300` is used ~50/50 as a border
*and* as light ink on the navy header — inverting it would have broken six ink sites, so
the four borders that mattered were overridden instead. `--grey-400` was already 6.55:1.
No hue token was touched: colour *meaning* must not shift between themes.

### Three things that would have been wrong and weren't obvious

1. **The heatmap ramp inverts its meaning on a dark page.** Light→dark shading means an
   empty cell becomes the brightest thing on screen and the busiest cell disappears. The
   ramp now runs dark→light on dark, holding the invariant that more metal always reads as
   more salience against the ground. `--heat-0` is the flat card surface, which preserves
   the distinction the original comment was protecting — "nothing acquired" still reads
   differently from "a little acquired".
2. **The ramp was defined twice, in two languages.** `reports.css`'s legend gradient was
   `HEAT_STOPS[1..4]` hardcoded in CSS. Both now read `--heat-0`…`--heat-4` from
   `theme.css`, so **the legend can no longer drift from the cells it describes** — the
   duplication is gone rather than kept in sync.
3. **Five focus rings were navy with `outline:none`**, invisible against a dark field and
   with no fallback — an accessibility regression, not a cosmetic one. All now use the
   gold ring, the one focus style that already survived dark. A sixth, the spinner's
   `border-top-color`, was the only thing distinguishing it from a static ring.

### Mechanism

- **`theme.css`**, loaded fifth. The four ported sheets stay byte-identical.
- **Single dark payload** under `:root[data-theme="dark"]`, with the head script resolving
  the OS preference into an explicit attribute. Not the ledger's pure-CSS guarded form,
  which duplicates its whole payload between a media query and an attribute block — a
  divergence between those copies is a silent visual bug and there is no browser
  automation here to catch it. Cost: four lines of `matchMedia` for live OS flips.
- **`var()` inside SVG.** Presentation attributes parse as CSS, so `fill`, `stop-color`
  and inline `style` all resolve `var()` live — the chart series re-theme with **no
  redraw**, and it reaches the inline legend swatches that no stylesheet rule could have
  overridden without `!important`.
- **Delegated click listener**, registered once. `dashboard.js`'s `paint()` wipes
  `container.innerHTML` on mount, on every nav click, **and once more when
  `getNavCounts()` resolves** — a directly-bound listener dies on that guaranteed second
  repaint. Delegation meant `dashboard.js` and `login.js` needed **no change at all**.
- **Toggle outside the `user ?` branch**, so it exists on the login screen too.
- **Tile restyle is opt-in**: markup carries `tile-grid`/`tile` alongside the legacy
  classes; `theme.css` styles the compound selectors. Value-first is done with CSS
  `order`, so no template was restructured — and that is also the better a11y answer,
  since `order` changes visual order only and label-then-value is the better reading order.

## Errors / issues encountered

- **A verification gate reported a false failure.** The "no `!important` in theme.css"
  check counted two hits — both in my own comment prose explaining that the file uses
  none. Re-ran with comments stripped: zero in actual CSS.
- **A script-tag count read 2 instead of 1**, which would have meant the head script was
  wrongly a module. It was a quoting artefact in the inline Python; a clean regex over the
  file confirmed one `type="module"` and that the head script correctly has no `type`.
- No functional errors. The load order, specificity and re-render contract were all
  established before any code was written, which is why the tricky parts landed first time.

## Achievements

- Night mode across the whole app — chrome, all five screens, tables, forms, modals,
  banners, charts and the heatmap — plus a toggle that survives repaints and sign-out.
- **Light mode provably unchanged**, by two independent checks: the four ported sheets are
  byte-identical (`git diff --exit-code` passes), and `heatColor()` across the ramp returns
  output **byte-identical to the previous hardcoded implementation**.
- **Every rule mechanically confined**: a parser over `theme.css` confirms each rule is
  either `[data-theme="dark"]`-prefixed or one of the four new classes.
- **Zero `!important`** — the attribute prefix carried enough specificity everywhere,
  including over the ID-specificity rule at `reports.css:220`.
- **Contrast verified quantitatively**, not by eye: every dark ink token clears 4.5:1
  (lowest 6.55), every chart series clears 3.0 (lowest 7.15), the worst
  `FLOW_COLORS_DARK` entry is 3.25, and the heat ramp is **strictly ascending** —
  1.00 → 2.00 → 3.25 → 7.15 → 12.50 — so the "more metal = more salience" invariant holds
  as arithmetic, not as an intention.
- `color-scheme:dark` fixes the five native date pickers, `<select>` popups, placeholders
  and scrollbars in one declaration.
- Backend untouched: **270 tests still passing**. All nine touched JS modules parse.
- CLAUDE.md §7 amended, so the next reader finds the sanctioned exception written down
  rather than treating the whole change as a contract violation.

### Decisions taken this session

1. New `theme.css`; the four ported sheets stay byte-identical.
2. KPI cards take the ledger's tile look in **both** themes.
3. Default follows the OS; an explicit toggle choice persists and wins.
4. Toggle left of the user name and role pill; Sign out restyled to match it.
5. Full coverage in one pass.
6. Heatmap ramp inverts on dark.
7. CLAUDE.md §7 amended.
8. The app's 8px radius kept on the tile slab, tiles clipped inside it.

## Future things to implement / open questions

- **Not seen in a browser — and this is the one change where that matters most.** What the
  checks above cannot settle: the fourteen tint alphas, whether the inverted heat ramp
  actually *reads*, the bar-gradient fade, whether `color-scheme:dark` really fixed the
  native date pickers (browser-native, unobservable from CSS), the tile proportions, and
  the login screen's first impression. Worth a pass at 1440 / 767 / 400px in both themes,
  an OS flip with the tab open, a sign-out, and a nav click plus the `getNavCounts()`
  repaint with the toggle state intact.
- **Fixed in passing, flagged rather than silent:** `audit.js`'s diff legend swatch was
  `#fdf0d8` while the rule it documents uses `--amber-100` `#fef3c7`. They had already
  drifted; both now read the same token.
- **`--slate-300` is not inverted**, so hairlines read slightly bright on dark. Deliberate
  — inverting it breaks six ink sites — but revisit if it looks wrong.
- **The heatmap zero cell is the flat card surface**, which makes "no data" hard to
  distinguish from the card itself. Alternative if it reads badly: surface plus a 1px
  inset hairline.
- **Accepted losses, listed in `theme.css`:** light-fill/dark-ink chips of the same hue
  family (`.badge--p1..p6`, `.banner--info/--success/--warn/--locked`, `.pill-pending`,
  `.audit-badge--*`, `.status-dot--*`) read as bright accent chips on dark. Internally
  consistent, so legible. Deliberately no blanket `filter:` — filters on text are
  unpredictable and there is no browser check here to catch the result.
- **`wholeKg` is still private in `charts.js`** and `.chart-callout-text{fill:#fef08a}` is
  still a raw literal — both pre-existing, neither breaks on dark.
- Unchanged from earlier sessions: the `is_active` session hole; the
  `pc2.rcpl@gmail.com` → Royal Chain vs Aalishaan scope discrepancy; `ruff`/`mypy` missing
  from `.metal`; the revision write path still unbuilt.
