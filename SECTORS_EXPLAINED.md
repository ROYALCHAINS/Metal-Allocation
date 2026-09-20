# RMAS — Allocation Sectors vs Metal Flow Sectors

Two sector sets, one relationship between them, and one thing this document
cannot tell you.

---

## Up front: the sector names are not in the codebase

**I cannot list the individual sector names, and neither can any model reading
this repository.** They do not exist in any `.gs` or `.html` file. They live as
**data in the Metal Generator sheet**, read at runtime:

```
Config.gs  RANGES.ALLOCATION_SECTORS = 'A7:C25'   (Priority | Sector | Purity)
Config.gs  RANGES.FLOW_SECTORS       = 'I7:I14'   (Sector)
```

`DataService.gs` carries the comment *"Sector definitions (read from Metal
Generator — never invented)"*, and that is the design: adding a sector is a sheet
edit, not a code change.

The only party-like strings anywhere in the code are in `Config.gs`, and they are
**operator scope assignments, not the sector lists**:

```javascript
OPERATOR_PARTIES: {
  'pc2.rcpl@gmail.com':   ['Aalishaan'],
  'godnooblm10@gmail.com': ['RC']
},
OPERATOR_FLOW_SECTORS: {
  'pc2.rcpl@gmail.com':   ['Aalishaan'],
  'godnooblm10@gmail.com': ['Royal Chain']
}
```

To get the real lists, run the extraction prompt in `DATABASE_OVERVIEW.md`
against the Metal Generator sheet, or run `inspectMetalGeneratorLayout()` from
`DiagnosticsService.gs` and read the execution log.

Everything below describes the **structure and the relationship**, which *are* in
the code.

---

## 1. The two sets are genuinely different

| | **Allocation sectors** | **Metal Flow sectors** |
|---|---|---|
| Meaning | **Demand** — what each production sector needs | **Supply** — metal physically arriving |
| Sheet range | `A7:C25` | `I7:I14` |
| Row count | 19 by range, 21 by `EXPECTED` — **unresolved** | 8 |
| Columns | Priority, Sector, Purity (+ Party added later) | Sector (+ Party beside it) |
| Has priority? | Yes — drives display order | No |
| Has purity? | Yes | No |
| Ledger | Metal Master | Metal Flow Master |
| Row fields | `previousRequirement`, `todayRequired`, `alloted`, `balance` | `acquired` |
| Read by | `readAllocationSectorDefinitions_()` | `readFlowSectorDefinitions_()` |
| Config labels | `MASTER_LABELS` | `FLOW_LABELS` |
| Scope resolved by | `OPERATOR_PARTIES` | `OPERATOR_FLOW_SECTORS` |
| Scope filter | `filterRowsByScope_()` | `filterFlowRowsByScope_()` |

They are separate ranges, separate sheets, separate read paths, separate scope
maps and separate filter functions. **Nothing in the code merges them.**

`ReportService.gs` makes the consequence explicit on the dashboard:

```javascript
// Metal Flow has its own sector list, so allocation-sector filters must not
// silently blank the acquired series.
```

If a sector name appears in both lists, those are **two distinct records** that
happen to share a label.

---

## 2. How they connect — through party, not sector

This is the part your question is really about, and the answer is structural.

**There is no sector-to-sector mapping table anywhere in the system.** No config
entry maps a flow sector to an allocation sector. The join is:

```
Metal Flow sector  ──(named after)──▶  PARTY  ──(owns)──▶  many allocation sectors
```

The Metal Flow list is **keyed by party name**. `Config.gs` states this directly:

> *"The Metal Flow table is keyed by party name rather than by order type, so an
> operator is mapped straight to the Metal Flow sector(s) they own."*

So when you say *"Metal Flow sector Royal Chain has been mapped to allocation
sectors"* — the mechanism is:

1. `Royal Chain` is a **flow sector**, and it is a flow sector *because* Royal
   Chain is a party that receives metal.
2. The **Party column in Metal Generator** marks which allocation sectors belong
   to Royal Chain.
3. Metal acquired under flow sector `Royal Chain` is therefore the supply pool
   available to *every* allocation sector whose Party is Royal Chain.

**One flow sector → one party → many allocation sectors.** The relationship is
one-to-many, and it is expressed entirely by the Party column. Change a sector's
party in the sheet and the mapping changes with it — no code edit.

### Why the dashboard is the only place they meet

`getDashboardSummary()` is the one function that reads both ledgers, and it keeps
them apart even there:

```javascript
flowKeysPresent  = set of sectorKeys present in the scoped flow rows
flowFilterActive = any selected sector key exists in flowKeysPresent
// sector filter applies to flow rows ONLY when flowFilterActive
```

Selecting an allocation sector must not blank the acquired series, because that
name will not exist in the flow list. Allocation rows are filtered
unconditionally; flow rows only when the key is actually a flow key.

---

## 3. How a name becomes a key

Both sets normalise through the same function, `ValidationService.gs`:

```javascript
function normalizeSectorKey_(name) {
  return String(name ?? '')
    .replace(/[\u2010-\u2015\u2212]/g, '-')  // en/em dash, minus → hyphen
    .replace(/\s+/g, ' ')                    // collapse runs of whitespace
    .trim()
    .toLowerCase();
}
```

`normalizePartyKey_()` in `DataService.gs` is a direct alias of it, so parties and
sectors share one normalisation rule.

**Note what it does and does not do.** It lowercases, trims, unifies dash
characters and collapses *repeated* whitespace. It **does not remove single
spaces**. So:

| Input | Key |
|---|---|
| `Royal Chain` | `royal chain` |
| `royal  chain` | `royal chain` |
| `RoyalChain` | `royalchain` ← **does not match the above** |
| `Royal–Chain` (en dash) | `royal-chain` ← **also does not match** |

The `Config.gs` comments claim matching happens *"ignoring spacing and dash
style"*. That overstates it: dash *style* is unified, but dash-versus-space is
not, and removing a space breaks the match. Spelling must be consistent between
the sheet and the config.

The party list itself is **derived, not declared** — `readPartyDefinitions_()`
collects distinct parties from the allocation definitions first, then the flow
definitions.

---

## 4. A live inconsistency in the current config

Look at the two maps side by side for the same operator:

```javascript
OPERATOR_PARTIES:      { 'godnooblm10@gmail.com': ['RC'] }
OPERATOR_FLOW_SECTORS: { 'godnooblm10@gmail.com': ['Royal Chain'] }
```

Normalised, those are **`rc`** and **`royal chain`** — different keys.

That operator's **allocation** scope resolves against a party literally named
`RC`, while their **flow** scope resolves against a flow sector named
`Royal Chain`. For this to work, the Metal Generator Party column must contain
`RC` for their allocation sectors *and* the flow list must contain `Royal Chain`.

If the Party column actually says `Royal Chain`, then `getUserScope_()` finds no
matching party, `parties` comes back empty, and every report returns
`NO_PARTY_ASSIGNED` — *"No party is assigned to your account"* — while their
Metal Flow view still works. That failure is silent and looks like a permissions
bug rather than a spelling one.

Compare the other operator, where both maps read `Aalishaan` and the two agree.

**Worth checking against the sheet before the port.** Either `RC` is a real party
name and this is correct, or it is an abbreviation that should read
`Royal Chain`. I can't tell from the code which.

---

## 5. What this means for the database

The port keeps them as two tables, joined through `party`:

```
                    ┌─────────────┐
                    │    party    │   ← derived from Metal Generator
                    └──────┬──────┘
                    ┌──────┴──────┐
            ┌───────▼──────┐  ┌───▼────────────┐
            │    sector    │  │  flow_sector   │
            │ priority     │  │                │
            │ purity       │  │  (8 rows)      │
            └───────┬──────┘  └───┬────────────┘
                    │             │
        ┌───────────▼──┐      ┌───▼──────────────────┐
        │ metal_master │      │  metal_flow_master   │
        │   DEMAND     │      │       SUPPLY         │
        └──────────────┘      └──────────────────────┘
```

Merging them into one table with a `type` flag would force `priority` and
`purity` nullable and invite joins that silently mix demand with supply. Keep
them separate.

Two things to settle before seeding:

1. **The allocation sector count** — 19 by range, 21 by `EXPECTED.ALLOCATION_ROWS`
   and `VersionCheck.gs`. `STRICT` is `false`, so the app has been warning and
   proceeding with whatever the sheet holds. The sheet is the only authority.
2. **Whether `RC` and `Royal Chain` are the same party**, per section 4.

Seed `party` first, then both sector tables referencing it, using the exact
strings from the sheet.
