# Session: Full RMAS schema — reference data, ledgers, audit, staging, idempotency

Date: 2026-09-20

Goal: Resolve the remaining open questions (scope tables, sector count, seed data,
one-view-vs-two) to unblock the backend, then implement what those answers unlock.

## Decisions taken this session

Asked four questions; three were answered:
- **Seed data / schema** → the user supplied `DATABASE_OVERVIEW.md` and `schema.sql`, a
  complete SQLite design for the whole system. This supersedes the CSV/paste options I
  offered.
- **Scope tables** → two join tables, keeping the null-fallback rule. `schema.sql`
  already implements exactly this (`user_party_scope` + `user_flow_scope`, with "when
  absent, fall back to the sector's party").
- **Daily view** → one role-conditional view, mirroring legacy's single Daily Allocation
  screen. (Not built yet — recorded for when the view is ported.)
- **Legacy quirks (idempotency on revise / operator carry-forward asymmetry / `'Any'`
  purity)** → **not answered.** Still open; treating "replicate legacy exactly" as the
  safe default until told otherwise, per CLAUDE.md's "the legacy source wins".

## What happened

1. Read the legacy source before proposing anything, which surfaced two facts that
   changed the design discussion:
   - **Parties are not an independent list in legacy.** `readPartyDefinitions_()` derives
     the distinct party set by scanning the Party column of the sector rows. `schema.sql`
     correctly promotes it to a real table.
   - **`OPERATOR_FLOW_SECTORS` has null-fallback semantics.** `getUserScope_()` returns
     `flowSectorKeys: null` when an operator has no entry, and `scopeAllowsFlow_()` then
     matches on party. So *zero rows means "derive from party", not "no access"* — a trap
     if modelled naively as a join table. This is now called out in `models/user.py`,
     `repository/user_repo.py`, `services/scope_service.py` and covered by tests.
2. **Reviewed the supplied schema rather than implementing it blindly**, and found three
   things needing a departure (all documented in the relevant model docstrings and in
   CLAUDE.md rule 17a, not applied silently):
   - `app_user` has **no password column** — `schema.sql` predates the username/password
     decision. Added `password_hash`.
   - `metal_allocation_audit_log.action_type`'s CHECK lists only the six `AUDIT_ACTIONS`
     from `AuditService.gs`, **omitting the three `StagingService.gs` writes to the same
     log** (`SUBMIT_REQUIREMENT`, `BLOCKED_RESUBMISSION`, `FAILED_SUBMISSION`, lines
     28-33/471/509/541). Left as-is, every operator-submission audit write would be
     rejected at runtime once staging is ported. Widened to all nine.
   - `metal_requirement_staging.status` defaults to `'PENDING'`, which is **not a legacy
     value** — `STAGING_STATUS` is `SUBMITTED`/`CONSUMED` only, and
     `markStagingConsumed_()` only matches `SUBMITTED`, so `PENDING` rows would be
     silently skipped at commit. Changed to the legacy vocabulary with a CHECK.
3. **The integer-grams decision in `schema.sql` is a better answer than mine.** Last
   session I flagged that SQLite has no exact decimal type and proposed
   `Numeric(12,3,asdecimal=True)` plus a round-trip test. Storing integer grams is
   lossless *by construction* (3 decimals of a kg is exactly 1 gram) rather than
   depending on driver behaviour. CLAUDE.md's Critical Rules item 1 was rewritten around
   it.
4. Implemented 8 model files: `party.py`, `sector.py` (Sector + FlowSector), `user.py`
   (AppUser + UserPartyScope + UserFlowScope), `allocation.py`, `flow.py`, `audit.py`,
   `staging.py`, `idempotency.py`.
5. Implemented `services/weight_service.py` — the single conversion boundary
   (`kg_to_grams`/`grams_to_kg`/`round_kg`/`nearly_equal`/`is_within_max`). It **refuses
   a float argument outright** rather than converting it.
6. Rewrote `services/scope_service.py` with a `UserScope` dataclass mirroring legacy's
   `getUserScope_()` return shape, plus `scope_allows_party`/`scope_allows_flow`.
7. Migration `0002` creates all 11 tables, 13 indexes, 2 append-only triggers and 3 views
   — **and copies the existing account across from 0001's `users` table before dropping
   it**, so the login created earlier in the day kept working rather than being discarded.
   Backed the DB up to the scratchpad first.
8. Updated everything referencing the old model: `repository/user_repo.py`,
   `routers/deps.py`, `routers/auth.py`, `schemas/auth.py`, `create_user.py`.
   `create_user.py` no longer calls `Base.metadata.create_all()` — the schema now comes
   from Alembic only, and `create_all` would have produced a divergent schema with no
   triggers or views.
9. The API contract stayed stable: `/auth/me` still returns `role: "admin"|"operator"`,
   now derived server-side from `is_admin` AND the deny list, so the frontend needed no
   change and a denied admin correctly reports as an operator.

## Errors / issues encountered

- **All 14 audit tests failed initially** with `no such table`. Root cause was a real
  design flaw in `migrations/env.py`, not the test: it **unconditionally overwrote**
  `sqlalchemy.url` with `settings.database_url`, so the test's temp-file URL was ignored
  and the migration ran against the live `rmas.db` (already at head → no-op). Fixed so a
  caller-supplied URL wins and Settings is only a fallback — which also means Alembic can
  now be pointed at another database at all.
- Briefly added a junk `_unused` column to `models/idempotency.py` purely to justify an
  import. Caught and removed before it reached a migration — it would have created a real,
  pointless column.
- Fixed an Alembic `path_separator` deprecation warning in `alembic.ini` while there.

## Achievements

- **70/70 tests pass** (up from 26), including new suites that prove behaviour rather than
  assert intent:
  - `test_weight_service.py` — exact kg↔grams round-trips, 1000-iteration accumulation
    without drift, `ROUND_HALF_UP` at the third decimal (vs. banker's rounding), float
    rejection, the `0.0005` epsilon, the `MAX_WEIGHT_KG` ceiling.
  - `test_audit_append_only.py` — runs the **real Alembic migration** against a temp
    database and proves the triggers actually abort UPDATE and DELETE, that all nine
    legacy action types are accepted, that an unknown one is rejected, and that a
    malformed date (`17/08/2026`) is rejected by the CHECK.
  - `test_scope_service.py` — deny-overrides-admin, denied admin gets operator scope,
    and both directions of the flow null-fallback rule.
- Verified against the real database, not just fixtures: 11 tables + 3 views + 2 triggers
  present, the account migrated with `is_admin=1` and its hash intact, and a login attempt
  with a deliberately wrong password correctly rejected by the real server.

## Follow-up: first reference data loaded (same day)

The user supplied 8 sector names: Royal Chain, Aalishaan, Aqua, ARK, IHG, Titan, Malabar,
Aditya Birla.

- **Identified them as FLOW sectors, not allocation sectors**, and confirmed before
  writing anything: the count matches `EXPECTED.FLOW_ROWS: 8` and `RANGES.FLOW_SECTORS:
  'I7:I14'` (8 rows) exactly, and `Aalishaan`/`Royal Chain` appear verbatim in
  `Config.gs`'s `OPERATOR_FLOW_SECTORS`. Confirmed by the user.
- **Party per flow sector**: confirmed by the user as party name = sector name, giving 8
  parties. Legacy read this from a Party column beside the flow list, falling back to
  `FLOW_SECTOR_PARTIES` (which is `{}`), and commented "Metal Flow is keyed by party
  name" — but `flow_sector.party_id` is NOT NULL, so this needed an explicit answer
  rather than an inference.
- **Found a second documentation error in DATABASE_OVERVIEW.md.** It states sector/party
  keys are "lowercase, with spaces, dashes and punctuation removed... mirrors the legacy
  normalizeSectorKey_()". It does not: `ValidationService.gs:70-76` collapses whitespace
  runs, converts unicode dashes to hyphens, trims and lowercases — it keeps spaces and
  punctuation. `'Royal Chain'` → `'royal chain'`, not `'royalchain'`. Following the
  overview would make `'Royal Chain'` and `'RoyalChain'` collide into one key, which
  legacy treats as two distinct sectors. Resolved in favour of the legacy source per
  CLAUDE.md, documented in `services/validation_service.py` and pinned by tests.
- Created `services/validation_service.py` (partial port — normalisation helpers only),
  `seed/flow_sectors.csv`, `seed/README.md` and `rmas/seed_reference_data.py`.
- **Names live in CSV, not in code**, per CLAUDE.md rule 15 ("never hard-code a sector
  name, party name, or purity value anywhere in the codebase") — the loader contains
  logic only.
- The loader refuses to guess on the allocation side: it raises with an explanatory error
  on a non-integer `priority` (the column is INTEGER NOT NULL but legacy read priority as
  a string cell) or a blank `purity` (TEXT NOT NULL, where legacy substituted `'Any'` —
  still an unanswered open question), rather than coercing either.
- Verified: dry-run first, then loaded — 8 parties + 8 flow sectors in the real database,
  correct keys, and **re-running produced no duplicates** (idempotent on normalised key).
- Test count 70 → 88 (added `tests/test_validation_service.py`).

## Follow-up: allocation sectors loaded — 19-vs-21 RESOLVED (same day)

The user supplied `seed/sector names.csv` (columns `Priority,Party,Sector,Purity`).

- **The count is 21.** `EXPECTED.ALLOCATION_ROWS: 21` was correct all along; the
  `RANGES.ALLOCATION_SECTORS: 'A7:C25'` comment (19 rows) and `Index.html`'s static
  "19 sectors" chip are both stale. CLAUDE.md's "Known legacy inconsistencies" entry is
  now marked resolved. **A long-standing open question closed by data, not by guesswork.**
- Profiled the file before loading: 21 rows, no duplicate sector names, purity uniformly
  `Any` (so the blank-purity/`'Any'`-fallback question never arose for this data), three
  parties — Royal Chain (10), Factory (8), Aalishaan (3), with **Factory new** (not among
  the 8 flow parties).
- **Priority: initially parsed to INTEGER, then reverted to verbatim TEXT** — see the
  correction below.
- Loader extended to accept the sheet export's own filename and header labels
  (`Priority`/`Party`/`Sector`/`Purity`) rather than forcing a rename. Noted in code why
  this is not a violation of CLAUDE.md rule 16: that rule drops *runtime* header detection,
  and the database schema stays explicit — this is a one-off import of sheet data.
- **Previewed inside a rolled-back transaction and showed the exact 21 parsed rows before
  committing anything**, rather than loading and inspecting afterwards.
- Final state: 9 parties, 21 allocation sectors, 8 flow sectors. Test count 88 → 108
  (added `tests/test_seed_reference_data.py`).
- Caught and corrected a reporting error of my own: a `LEFT JOIN` across both sector
  tables multiplied rows and produced bogus per-party counts (Royal Chain "10 flow
  sectors"); recounted with subqueries before reporting.

## Correction: priority stored as verbatim TEXT, and `RC` means Royal Chain

The user clarified two things, both of which corrected earlier assumptions of mine.

**1. `RC` is an abbreviation for Royal Chain.** I had flagged `Config.gs`'s
`OPERATOR_PARTIES: {'godnooblm10@gmail.com': ['RC']}` as "stale config matching no party".
Wrong conclusion — `RC` is simply how Royal Chain is abbreviated throughout the sector
names (`RC Customer Orders`, `RC Corp - …`), and the sheet's Party column already maps
those sectors to Royal Chain correctly. The operator should map to the Royal Chain
`party_id`; **`RC` must not be loaded as a separate party.** (Still worth noting for the
port that legacy's own string match would have failed here, since
`normalizePartyKey_('RC')` = `rc` ≠ `royal chain`.) Corrected in `seed/README.md` and
memory.

**2. Priority is a string and must stay one.** I had parsed `Priority 1` → integer `1`,
justified by `schema.sql`'s `INTEGER NOT NULL`. Investigating `ReportService.gs` before
re-deciding showed that was the wrong trade: priority is **user-visible**, used as the
report filter-dropdown label (line 204: `{ label: r.priority, key: pk }`), the "by
priority" dashboard grouping key (line 587), and in text search (line 107) — all on the
literal string. Also found that `Scripts.html`'s `priorityClass()` (which extracts the
digit for `.badge--p1`…`p6`) is **dead code, never called**, and that the Daily Allocation
table renders no priority column at all.

The user chose verbatim TEXT. So `sector.priority` and `metal_master.priority_snapshot`
became `TEXT` (migration `0003`) and hold exactly what the sheet says. `parse_priority()`
was replaced by `read_priority()`, which trims and nothing else. This is a **fourth**
documented departure from `schema.sql`, recorded in CLAUDE.md rule 17a.

**Migration 0003 failed on the first attempt**, and the failure mode is worth recording:
SQLite cannot alter a column type in place, so Alembic batch mode rebuilds the table —
create copy, drop original, rename — but the rename aborts with
`error in view v_allocation_kg: no such table: main.sector`, because a VIEW referencing
the table is validated during the rename. Fixed by dropping the three views before the
batch alters and recreating them after. Two further observations from the failed run:
- Alembic correctly left `alembic_version` at `0002` and the `sector` data intact, but
  **left an empty `_alembic_tmp_sector` table behind**. The fixed migration now drops any
  such leftover first, so it is safe to re-run after a failure.
- The re-seed that ran after the failure *appeared* to succeed in writing
  `'Priority 1'` into a column still declared `INTEGER` — because **SQLite uses type
  affinity, not strict typing**, and silently stored the string. A good reminder that the
  declared type alone proves nothing on SQLite; the migration had to actually be fixed.

Verified afterwards: `alembic_version` = `0003`, `priority TEXT NOT NULL`, all six values
present verbatim, all three views restored, no leftover temp tables, 21 rows intact. The
full suite (100 tests) also exercises `alembic upgrade head` against a **fresh** temp
database in the audit-log fixture, so the clean-install path is covered too, not just the
in-place alter.

## Future things to implement / open questions

- **All reference data is now loaded.** Nothing is blocked on missing sector/party data
  any more.
- When populating `user_party_scope`, map the `'RC'` operator to **Royal Chain**.
- No operator accounts or `user_party_scope`/`user_flow_scope` rows exist yet, so operator
  scoping is untested against real data. Only one admin account exists.
- The three legacy quirks (revise idempotency, operator carry-forward asymmetry, `'Any'`
  purity) remain unanswered — though the purity one is now moot for this dataset, since
  every row carries a literal `Any`.
- **The three legacy quirks were never answered** (see Decisions above) — defaulting to
  faithful replication.
- `priority` is `INTEGER NOT NULL` in the schema, but legacy reads priority as a *string*
  cell. If the sheet contains a non-integer priority, the load will fail — the extraction
  prompt already asks about this, so it should be checked when the data arrives.
- `purity` is `TEXT NOT NULL`, so legacy's `'Any'` fallback for a blank Purity cell is
  still needed at load time unless the data has no blanks (ties into the unanswered
  quirks question).
- No seed/import script exists yet — write one when the extracted data arrives.
- Next code candidate remains `services/validation_service.py` (`computeTotals_`, the
  balance arithmetic), which can now be written against `weight_service` in grams.
