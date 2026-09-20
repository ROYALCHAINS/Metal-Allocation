# RMAS — Metal Generator Extraction & Database Overview

Two things here: a prompt for extracting the reference data out of the Metal
Generator sheet, and a high-level map of how the tables fit together.

The SQLite DDL is in `schema.sql`.

---

## Part 1 — Extraction prompt for Metal Generator data

Paste this into a fresh chat with the Metal Generator sheet attached (export it
as CSV or XLSX first). It is written to stop the model inventing anything.

---

> I am migrating the Royal Metal Allocation System from Google Sheets to SQLite.
> Attached is the **Metal Generator** sheet, which holds all reference data.
>
> Extract the data exactly as it appears. **Do not invent, infer, correct,
> normalise, reorder or "tidy" any name, number or value.** If a cell is blank,
> report it as blank. If something is ambiguous, list it as a question at the end
> rather than guessing.
>
> **The sheet layout is not fixed.** Columns have been inserted and moved over
> time, so locate each field by its **header text**, not by column position.
> Accepted header labels:
>
> - Priority → `Priority`
> - Party → `Party`, `Party Name`
> - Sector → `Sector`, `Sector Name`
> - Purity → `Purity`
>
> Scan the first 12 rows for the header row before assuming where data starts.
>
> **Extract two separate lists.**
>
> **A — Allocation sectors.** Historically read from range `A7:C25`, with a Party
> column added later. For each row give me: priority, sector name, purity, party
> name, and the row number it came from.
>
> **B — Flow sectors.** A different and smaller list, historically at `I7:I14`,
> with a party column beside it. For each row give me: sector name, party name,
> and the row number.
>
> These two lists are **separate sets and must never be merged.** A name may
> appear in both; treat those as distinct records.
>
> **Report the exact count of each list.** There is a known discrepancy in the
> configuration — one place says 19 allocation sectors, another says 21. Tell me
> what the sheet actually contains. Do not pad or truncate to match either number.
>
> **Then report:**
> 1. Every distinct party name across both lists, exactly as spelled.
> 2. Any duplicate sector names within either list.
> 3. Any row with a missing priority, purity or party.
> 4. Any priority value that is not a whole number, and whether priorities are
>    unique or repeat across sectors.
> 5. The exact format purity is written in (`75%`, `0.75`, `22K`, mixed?).
> 6. Any row that looks like a heading, total, note or blank separator rather
>    than a sector.
>
> **Output format.** Three markdown tables — allocation sectors, flow sectors,
> parties — then a short list of anything that needs my decision. No SQL yet.

---

### Follow-up prompt, once the extraction is verified

> Now generate SQLite `INSERT` statements for the tables `party`, `sector` and
> `flow_sector` in the attached `schema.sql`.
>
> Rules:
> - Insert parties first, then reference them by `party_id`.
> - `party_key` and `sector_key` are the normalised form of the name: lowercase,
>   with spaces, dashes and punctuation removed. This mirrors the legacy
>   `normalizeSectorKey_()` matching, which was case- and spacing-insensitive.
> - `purity` is stored verbatim as TEXT — do not convert it to a number.
> - `display_order` follows the sheet's row order.
> - Use the exact names from the extraction. No new sectors, no renames.

---

## Part 2 — Database overview

### The shape of it

Three reference tables describe *what exists*. Two ledgers record *what happened
on a date*. One append-only log records *who changed what*.

```
                    ┌─────────────┐
                    │    party    │
                    └──────┬──────┘
                    ┌──────┴──────┐
                    │             │
            ┌───────▼──────┐  ┌───▼────────────┐
            │    sector    │  │  flow_sector   │
            │  (19 or 21)  │  │      (8)       │
            │ priority     │  │                │
            │ purity       │  │                │
            └───────┬──────┘  └───┬────────────┘
                    │             │
        ┌───────────▼──┐      ┌───▼──────────────────┐
        │ metal_master │      │  metal_flow_master   │
        │  DEMAND      │      │      SUPPLY          │
        │  per date    │      │      per date        │
        └───────┬──────┘      └───┬──────────────────┘
                │                 │
                └────────┬────────┘
                         │
        ┌────────────────▼──────────────────┐
        │  metal_allocation_audit_log       │
        │  append-only, JSON before/after   │
        └───────────────────────────────────┘
```

### Why two sector tables and not one

`sector` and `flow_sector` are different sets with different sizes, different
columns and different meanings. Allocation sectors carry priority and purity and
represent **demand**. Flow sectors carry neither and represent **supply** — metal
arriving. The legacy sheet kept them in separate ranges (`A7:C25` and `I7:I14`)
for that reason.

A name may legitimately appear in both lists. Merging them into one table with a
type flag would force nullable priority and purity columns and invite joins that
silently mix demand with supply.

### The tables

| Table | Holds | Grain |
|---|---|---|
| `party` | Party names, normalised keys | one row per party |
| `sector` | Allocation sectors: priority, purity, owning party | one row per sector |
| `flow_sector` | Flow sectors and owning party | one row per flow sector |
| `app_user` | Emails, display names, admin flag, deny flag | one row per user |
| `user_party_scope` | Which operator sees which party | many-to-many |
| `user_flow_scope` | Explicit flow-sector grants | many-to-many |
| `metal_master` | Daily allocation ledger | **one row per (date, sector)** |
| `metal_flow_master` | Daily supply ledger | **one row per (date, flow_sector)** |
| `metal_allocation_audit_log` | Every save, revision and failure | one row per action |
| `metal_requirement_staging` | Operator submissions awaiting commit | one row per (date, sector, operator) |
| `request_log` | Idempotency guard | one row per request ID |

### How the connection works in practice

The daily screen for a given date is one query per ledger:

```sql
-- Demand side, scoped to the parties this operator may see
SELECT s.priority, s.sector_name, m.purity_snapshot,
       m.previous_requirement_g, m.today_required_g,
       m.alloted_g, m.balance_g
FROM metal_master m
JOIN sector s ON s.sector_id = m.sector_id
WHERE m.allocation_date = ?
  AND m.party_id IN (SELECT party_id FROM user_party_scope WHERE user_id = ?)
ORDER BY s.priority, s.display_order;
```

Scope is applied in the `WHERE` clause on **every** query. Never filter in the
application after fetching everything.

### Back-dated lookups — the carry-forward rule

This is why `allocation_date` is TEXT in `YYYY-MM-DD`: it sorts
lexicographically, so date ranges and "most recent before X" are plain SQL
against an index.

```sql
-- Rule date: Monday looks back to Saturday, otherwise yesterday.
-- Computed in the application, then:
SELECT sector_id, balance_g
FROM metal_master
WHERE allocation_date = :rule_date;

-- Fallback when nothing was saved on the rule date
-- (RULES.CARRY_FORWARD_FROM_LATEST_SAVED = true):
SELECT MAX(allocation_date)
FROM metal_master
WHERE allocation_date < :selected_date;
```

That second query is what stops a skipped day silently resetting balances to
zero. It is covered by `idx_master_date`.

Each ledger and the audit log carries its own `allocation_date`, so any of them
can be filtered to a date or a range independently — no join required to answer
"what happened on the 14th".

### Revisions

A revision **replaces** that date's rows, matching the legacy
`deleteRowsForDate_()` + `appendBothMasters_()` behaviour. The
`UNIQUE (allocation_date, sector_id)` constraint enforces the grain, and
`revision_number` increments. The full before-and-after state is written to the
audit log as JSON, so nothing is actually lost by the replacement.

---

## Part 3 — Two decisions before you load data

**1. Weights are stored as INTEGER grams, not REAL kilograms.**

SQLite has no exact decimal type, and REAL is binary floating point. Since the
legacy system worked in kilograms to exactly three decimals, and three decimals
of a kilogram is precisely one gram, storing grams as integers is lossless and
exact. Columns carry a `_g` suffix. Convert at the application boundary into
`Decimal`, never `float`. The `v_allocation_kg` and `v_flow_kg` views handle
presentation.

**2. The sector count must be settled first.**

The configuration contradicts itself — `A7:C25` is 19 rows and the comment beside
it says 19, but `EXPECTED.ALLOCATION_ROWS` is 21 and `VersionCheck.gs` refers to
21 sectors. Because `STRICT` is `false`, the app has been warning and carrying on
with whatever the sheet holds. **The sheet is the only authority.** The extraction
prompt above asks for the real count explicitly.
