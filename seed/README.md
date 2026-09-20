# Reference data

Sector, party and purity values are **data, not code** (CLAUDE.md section 6, rule 15) —
they live here as CSV and are loaded into the database by `rmas/seed_reference_data.py`.
Never hard-code any of these names in a `.py` or `.js` file.

## Files

| File | Loads into | Source |
|---|---|---|
| `flow_sectors.csv` | `party`, `flow_sector` | **8 rows** — one per party, legacy range `I7:I14` (see below) |
| `sector names.csv` | `party`, `sector` | Metal Generator sheet, allocation list (**21 rows**) |

The loader accepts the allocation list as either `sector names.csv` (the sheet export's
own name) or `allocation_sectors.csv`, and reads columns by either the sheet's header
labels (`Priority`, `Party`, `Sector`, `Purity`) or snake_case equivalents.

## `sector names.csv`

**21 allocation sectors — this settled the long-standing 19-vs-21 discrepancy.**
`EXPECTED.ALLOCATION_ROWS: 21` was correct; the `A7:C25` range comment (19 rows) and
`Index.html`'s static "19 sectors" chip are both stale.

Priorities are `Priority 1`…`Priority 6` — six levels, matching `Styles.html`'s
`.badge--p1`…`.badge--p6`. Three parties: Royal Chain (10 sectors), Factory (8),
Aalishaan (3). Purity is `Any` on every row.

**Nothing is transformed.** Every value is loaded exactly as the sheet writes it. In
particular `priority` is stored verbatim as the string `Priority 1`…`Priority 6`
(`sector.priority` is `TEXT NOT NULL`, migration `0003`), because legacy shows that
wording to users — it is the report filter-dropdown label, the dashboard's "by priority"
grouping key, and part of text search. It is never parsed into a number. The
`.badge--p1`…`.badge--p6` CSS class is derived from the label in the browser, matching the
first digit as legacy's `priorityClass()` does.

The only rule the loader enforces is that NOT NULL columns cannot be blank — a blank
priority or purity is refused rather than filled in. See `read_priority()` and
`tests/test_seed_reference_data.py`.

## `flow_sectors.csv` — 8 rows

**The Metal Flow table is keyed by PARTY, not by order type.** Each row is a party that
metal physically arrives for, and maps to itself as its own party:

| Flow row | Party |
|---|---|
| Royal Chain | Royal Chain |
| Aalishaan | Aalishaan |
| Aqua | Aqua |
| ARK | ARK |
| IHG | IHG |
| Titan | Titan |
| Malabar | Malabar |
| Aditya Birla | Aditya Birla |

This matches legacy range `I7:I14` and `EXPECTED.FLOW_ROWS: 8`, and it is what
`Config.gs` means by *"the Metal Flow table is keyed by party name rather than by order
type, so an operator is mapped straight to the Metal Flow sector(s) they own."* The UI
labels this column **Party** on every screen.

The allocation list (`sector names.csv`) is untouched — 21 order-type sectors across
Royal Chain, Factory and Aalishaan. The two lists are separate sets with no shared
names, as `DATABASE_OVERVIEW.md` and `schema.sql` always said.

> **History:** between 2026-09-20 and 2026-09-21 this file held the 21 allocation sector
> names instead. Set by instruction, reverted, and set back to the 8 party names on
> 2026-09-21. The 21 names belong to the demand side only.

### Known consequence: Factory has no supply row

`Factory` owns 8 allocation sectors but is **not** one of the 8 Metal Flow parties, so no
acquisition can be recorded against it and an operator scoped to Factory sees an empty
Metal Flow table. Conversely Aqua, ARK, IHG, Titan, Malabar and Aditya Birla each have a
flow row but own no allocation sector.

Both are reported by `python seed_reference_data.py --report`. Loaded as supplied rather
than guessed at.

`display_order` follows the list order above.

## Pruning

The loader only inserts and updates, so removing a name from a CSV leaves the row behind
in the database. `--prune` deletes `flow_sector` rows absent from the CSV, making the file
authoritative:

```
python seed_reference_data.py --prune --dry-run   # report first
python seed_reference_data.py --prune
```

It is opt-in, and fails loudly if a row being removed is still referenced by
`metal_flow_master`, staging or `user_flow_scope` — reference data in use must not vanish
silently.

## Parties

Nine in total, from the union of both lists — matching legacy's
`readPartyDefinitions_()`:

- **Royal Chain** — 10 allocation sectors, 1 flow row
- **Factory** — 8 allocation sectors, **no flow row** (see above)
- **Aalishaan** — 3 allocation sectors, 1 flow row
- **Aqua, ARK, IHG, Titan, Malabar, Aditya Birla** — 1 flow row each, no allocation
  sectors

`Factory` is correct and stays (confirmed 2026-09-21). Six of its sectors name a brand
(`Fac Corp - Titan`, `ARK Orders`, …) — that brand is the customer the order is for, not
the owning business unit, so those rows are **not** to be re-parented.

Run `python seed_reference_data.py --report` to print the current mapping.

## `RC` means Royal Chain

`Config.gs`'s `OPERATOR_PARTIES` maps an operator to party `'RC'`. **`RC` is an
abbreviation for `Royal Chain`** (confirmed 2026-09-20) — the same abbreviation used
throughout the allocation sector names (`RC Customer Orders`, `RC Corp - Reliance`,
`RC IMS - Machine Chain`, …), all of which correctly carry party `Royal Chain` in the
sheet's Party column.

Worth knowing for the port: legacy matched party scope on the *normalised* name, and
`normalizePartyKey_('RC')` is `rc`, which does **not** equal `royal chain`. So that config
entry would not have matched by string comparison. When populating `user_party_scope`, map
that operator to the **Royal Chain** party by `party_id` — the abbreviation is not a
separate party and must not be loaded as one.

## Resolved — `Factory` is a real party

**Confirmed 2026-09-21: `Factory` is correct and stays.** All eight of its sectors keep
`Factory` as their party on both the demand and supply sides, exactly as the supplied
mapping states. Do not re-parent them.

Six of those eight name a brand directly — `Fac Customer/Stock Orders - Aqua`,
`Fac Customer/Stock Orders - IHG`, `ARK Orders`, `Fac Corp - Titan`, `Fac Corp - Malabar`,
`Fac Corp - Aditya Birla` — which makes it tempting to move them onto the matching brand
party. **That would be wrong.** The brand in the name describes the *customer the order
is for*; the party is the *business unit that owns the order*, and that is Factory. The
remaining two, `Factory Rotation` and `NPD`, carry no brand at all, which is consistent
with the same reading.

### Consequence, accepted deliberately

`party` holds nine names but only three — Royal Chain, Factory, Aalishaan — are used by
any sector. **Aqua, ARK, IHG, Titan, Malabar and Aditya Birla own nothing on either
side.** They are kept because they are real parties in the business even though no sector
is currently assigned to them.

So an operator scoped to one of those six would see an empty screen on every page. That
is a data state, not a bug, and `python seed_reference_data.py --report` lists them under
"parties owning no sectors at all" on every run so it stays visible.
