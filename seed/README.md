# Reference data

Sector, party and purity values are **data, not code** (CLAUDE.md section 6, rule 15) —
they live here as CSV and are loaded into the database by `rmas/seed_reference_data.py`.
Never hard-code any of these names in a `.py` or `.js` file.

## Files

| File | Loads into | Source |
|---|---|---|
| `flow_sectors.csv` | `party`, `flow_sector` | **21 rows** — the allocation sector names, each mapped to a party (see below) |
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

## `flow_sectors.csv` — 21 rows

The same 21 sector names as the allocation list, each mapped to its **party** — taken
from `sector names.csv`'s Party column, deliberately *not* mapped to themselves.

> **This overrides the "never merge the two" rule** in `DATABASE_OVERVIEW.md` and
> `schema.sql`, and `EXPECTED.FLOW_ROWS: 8` no longer describes this table. Set by
> explicit instruction (2026-09-20), briefly reverted to the legacy 8 party names on
> 2026-09-21 and reinstated the same day. See CLAUDE.md rule 17a.

The rows remain distinct records from their allocation namesakes: one is demand, one is
supply, and nothing joins them by name. The join between the two ledgers is the
**party**, one-to-many.

**Superseded:** the table originally held the 8 Metal Flow names from legacy range
`I7:I14` (Royal Chain, Aalishaan, Aqua, ARK, IHG, Titan, Malabar, Aditya Birla), each
being its own party.

`display_order` follows sheet row order.

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
`readPartyDefinitions_()`, which collected distinct parties across the allocation and
flow sector rows:

- **Royal Chain** — 10 allocation sectors, 10 flow sectors
- **Factory** — 8 allocation sectors, 8 flow sectors
- **Aalishaan** — 3 allocation sectors, 3 flow sectors
- **Aqua, ARK, IHG, Titan, Malabar, Aditya Birla** — present in `party` but currently
  own nothing on either side

Note those six brand names also appear *inside* Factory's sector names
(`Fac Corp - Titan`, `Fac Customer/Stock Orders - Aqua`, `ARK Orders`, …). Those rows
correctly carry `Factory` as their party, **not** the brand — confirmed 2026-09-21. See
"Resolved — `Factory` is a real party" at the end of this file.

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
