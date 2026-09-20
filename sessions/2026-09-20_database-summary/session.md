# Session: Database — consolidated record of changes and what was implemented

Date: 2026-09-20

Goal: A single consolidated record of the database work done on 2026-09-20, covering
what changed and what was implemented. The chronological detail lives in the other
`2026-09-20_*` session folders; this is the state-of-the-database summary.

**Current state at time of writing:** migration `0003`, 11 tables + `alembic_version`,
3 views, 2 triggers, 19 indexes, 107 tests passing.

---

## 1. What changes have been done

### Database engine changed: PostgreSQL → SQLite
- `DATABASE_URL` now defaults to a SQLite file at `rmas/rmas.db` (gitignored), resolved
  from `config.py`'s own location so it works regardless of the working directory.
- `psycopg[binary]` removed from `requirements.txt`. SQLite needs no driver (stdlib).
- `database.py` adds `check_same_thread: False` for SQLite, since FastAPI runs sync
  routes across threads.
- CLAUDE.md section 4 updated. Moving back to PostgreSQL is intended to be a
  `DATABASE_URL` change, not a rewrite — nothing above the repository layer knows which
  database is in use.

### Weights are stored as INTEGER GRAMS
- Not `REAL`, not `Numeric`, never `float`. Legacy worked in kilograms to exactly 3
  decimals, and 3 decimals of a kg is exactly 1 gram, so this is lossless *by
  construction* rather than dependent on driver behaviour.
- Columns carry a `_g` suffix (`alloted_g`, `balance_g`, `acquired_g`, `value_g`).
- This came from the supplied `schema.sql` and replaced an earlier, weaker proposal of
  mine (`Numeric(12,3,asdecimal=True)` plus a round-trip test).

### The `users` table was replaced by `app_user`
- Different shape: `is_admin`/`admin_denied` booleans instead of a role enum, plus
  `is_active` and `created_at`.
- **Existing accounts were migrated, not discarded** — migration `0002` copies rows across
  before dropping `users`, so the login created earlier in the day kept working.

### `priority` changed from INTEGER to TEXT (migration `0003`)
- Stored verbatim as `'Priority 1'`…`'Priority 6'`, exactly as the sheet writes it.
- Reason: legacy shows the string to users — `ReportService.gs` uses it as the report
  filter-dropdown label (line 204), the "by priority" dashboard grouping key (line 587)
  and in text search (line 107).
- Applies to both `sector.priority` and `metal_master.priority_snapshot`.

### The 19-vs-21 sector count was RESOLVED: **21**
- `EXPECTED.ALLOCATION_ROWS: 21` was right. The `A7:C25` range comment (19 rows) and
  `Index.html`'s static "19 sectors" chip are both stale. A question open since the very
  first review, closed by real data rather than guesswork.

### `flow_sector` now holds the same 21 names as `sector`
- Originally loaded with the 8 legacy Metal Flow names (each its own party); those were
  pruned on instruction.
- Now the 21 sector names, each mapped to its **real** party — Royal Chain 10, Factory 8,
  Aalishaan 3 — never to itself.
- This **overrides** `DATABASE_OVERVIEW.md`/`schema.sql`'s "never merge the two", and
  `EXPECTED.FLOW_ROWS: 8` no longer describes this table.

### Five documented departures from the supplied `schema.sql`
Recorded in CLAUDE.md rule 17a and in each model's docstring, never applied silently:
1. `app_user.password_hash` **added** — `schema.sql` predates the username/password
   decision, so login could not work without it.
2. `audit_log.action_type` CHECK **widened** from 6 values to 9 — `schema.sql` omitted
   `SUBMIT_REQUIREMENT`/`BLOCKED_RESUBMISSION`/`FAILED_SUBMISSION`, which
   `StagingService.gs` writes to the same log. Left as-is, every operator-submission audit
   write would have failed at runtime once staging is ported.
3. `staging.status` **changed** from `'PENDING'` to legacy's `SUBMITTED`/`CONSUMED` —
   `'PENDING'` is not a legacy value, and `markStagingConsumed_()` only matches
   `SUBMITTED`, so those rows would have been silently skipped at commit.
4. `priority` / `priority_snapshot` **TEXT not INTEGER** (above).
5. `flow_sector` **21 rows, not 8** (above).

`schema.sql` was deliberately **not** regenerated — it remains the design reference, and
is now out of date in these five places by choice.

---

## 2. What things got implemented

### Schema — 11 tables, 3 views, 2 triggers, 19 indexes

| Table | Rows now | Purpose |
|---|---|---|
| `party` | 9 | Party names + normalised keys |
| `sector` | 21 | Allocation sectors (demand): priority, purity, owning party |
| `flow_sector` | 21 | Flow sectors (supply) + owning party |
| `app_user` | 1 | Accounts: email, display name, admin flag, deny flag, password hash |
| `user_party_scope` | 0 | Which operator sees which party |
| `user_flow_scope` | 0 | Explicit flow-sector grants |
| `metal_master` | 0 | Daily allocation ledger — one row per (date, sector) |
| `metal_flow_master` | 0 | Daily supply ledger — one row per (date, flow_sector) |
| `metal_allocation_audit_log` | 0 | Every save, revision and failure |
| `metal_requirement_staging` | 0 | Operator submissions awaiting commit |
| `request_log` | 0 | Idempotency guard (replaces the legacy CacheService) |

Views: `v_allocation_kg`, `v_flow_kg`, `v_closing_balance_by_date` — kilograms for
presentation only, never compute on them.

### Append-only audit enforced by the database
`trg_audit_no_update` / `trg_audit_no_delete` abort any UPDATE or DELETE on the audit log.
Not convention — actual triggers, and `tests/test_audit_append_only.py` proves they fire
by running the real migration against a temp database.

### Reference data loading
- `seed/sector names.csv` (21 allocation sectors) and `seed/flow_sectors.csv` (21 flow
  sectors) — **names live in data files, never in code** (CLAUDE.md rule 15); the loader
  holds logic only.
- `rmas/seed_reference_data.py` — idempotent on normalised key, `--dry-run` to preview,
  `--prune` to make the CSV authoritative by deleting rows no longer in it.
- Refuses rather than guesses: a blank priority or purity raises with a message naming the
  offending sector, instead of inventing a value.

### Operator party scoping
- `repository/sector_repo.py` — the party filter is applied **in the SQL WHERE clause**,
  per `DATABASE_OVERVIEW.md`'s "never filter in the application after fetching
  everything". An operator with no grant **fails closed** (sees nothing, not everything).
- `services/scope_service.py` — `is_administrator()` (deny list always overrides an admin
  grant), `build_scope()`, `scope_allows_party()`, `scope_allows_flow()`. Flow access
  honours legacy's null-fallback rule: an explicit `user_flow_scope` grant wins, and only
  with no grant does it fall back to the sector's party. **Zero rows means "derive from
  party", not "no access".**
- `routers/sectors.py` — `GET /sectors` returns only what the caller may see. The client
  never states which party it wants.
- `create_user.py --party` (repeatable) grants an operator a party; refuses an unknown
  party name and lists the valid ones.

### Precision handling
`services/weight_service.py` is the only place kilograms become grams. It **refuses float
arguments outright** rather than converting them. `tests/test_weight_service.py` proves
exact round-trips, 1000-iteration accumulation without drift, `ROUND_HALF_UP` at the third
decimal (vs banker's rounding), the `0.0005` epsilon and the `MAX_WEIGHT_KG` ceiling.

### Key normalisation
`services/validation_service.py`'s `normalize_key()` ports `ValidationService.gs`'s
`normalizeSectorKey_()` exactly — collapses whitespace runs, folds unicode dashes to
hyphens, trims, lowercases. **Spaces are kept**, contradicting `DATABASE_OVERVIEW.md`'s
claim that keys have "spaces, dashes and punctuation removed"; the legacy source wins, and
tests pin it.

---

## Errors / issues encountered

- **Migration 0003 failed on first run.** SQLite cannot alter a column type in place, so
  Alembic batch mode rebuilds the table — but the final rename aborts with
  `error in view v_allocation_kg: no such table: main.sector`, because a VIEW referencing
  the table is validated during the rename. Fixed by dropping the three views before the
  batch alters and recreating them after. The failed run also left an empty
  `_alembic_tmp_sector` behind, so the migration now clears such debris first and is safe
  to re-run.
- **SQLite type affinity masked the problem.** After that failure, the re-seed *appeared*
  to write `'Priority 1'` successfully into a column still declared `INTEGER` — SQLite
  stores what it is given. The declared type alone proves nothing; the DDL had to be
  checked, not just the data.
- **`migrations/env.py` unconditionally overwrote `sqlalchemy.url`**, so Alembic could
  never be pointed at another database — which broke the first attempt at testing
  migrations. Fixed so a caller-supplied URL wins and Settings is only the fallback.
- Two self-inflicted slips caught before they mattered: a junk `_unused` column added to
  `models/idempotency.py` purely to justify an import (would have created a real, pointless
  column), and a duplicated `db.commit()` in `create_user.py`.
- A `LEFT JOIN` across both sector tables produced bogus per-party counts in a status
  report; recounted with subqueries before reporting the numbers.

---

## Future things to implement / open questions

- **No operator account exists**, so scoping is proven by tests but not yet by real use:
  `python create_user.py --email <op> --display-name "<name>" --role operator --party "Royal Chain"`
- Six parties (Aqua, ARK, IHG, Titan, Malabar, Aditya Birla) now own nothing after the
  flow_sector prune. Left in place deliberately — awaiting a decision on deletion.
- All ledger/staging/audit tables are empty; nothing writes to them yet.
- Three legacy quirks still unanswered: revise idempotency guard, operator carry-forward
  asymmetry, `'Any'` purity fallback (the last now moot — every row carries a literal
  `Any`).
- Next code candidate: `computeTotals_` / the balance arithmetic in
  `validation_service.py`, which can now be written against real sectors and the grams
  helpers.
