# Session: Daily Allocation — save path (the admin commit)

Date: 2026-09-20

Goal: Stage 2 of the Daily Allocation flow — `POST /allocations/{date}`: validate against
live definitions, write both ledgers, audit the result, and guard against double-writes.

## What happened

Read `AuditService.gs` (audit id format, snapshot shapes, `getLatestRevisionNumber_`) and
`Code.gs`'s `saveDailyAllocation` before writing, and followed its ordering exactly:
idempotency guard → admin check → validate + save rules → date re-check → write both
ledgers → audit.

### Implemented
- **`repository/audit_repo.py`** — INSERT only; there is deliberately no update or delete
  function, on top of the database triggers.
- **`services/audit_service.py`** — `AUD-yyyyMMdd-HHmmss-NNNN` ids, compact JSON snapshots
  using legacy's abbreviated keys (`p`/`s`/`pu`/`pr`/`tr`/`al`/`bl`), and **two** write
  functions: `write_entry()` where the audit is part of the decision, and
  `write_entry_safely()` which never raises — preserving legacy's "auditing must never
  block or reverse a completed business operation".
- **`repository/idempotency_repo.py`** — the `request_log` table with the 900s window and
  pruning on write, plus `release()` so a *failed* save doesn't lock an operator out of
  retrying (legacy's `cache.remove` in its failure path).
- **`validate_and_normalize_payload()`** — rebuilds every row from the live sector
  definitions.
- **`save_daily_allocation()`**, schemas and the `POST` route with a domain-error →
  HTTP-status map (routers own that translation; services never import `HTTPException`).

### Three things worth recording

**1. Security: the client supplies only weights.** Sector name, party, purity and priority
are all taken from the database, and submitted rows are matched by `sector_id` — so row
order cannot corrupt a save, a tampered payload cannot relabel a row or move it to another
party, and because the definitions passed in are already scope-narrowed, an operator can
only ever save rows for sectors they may see. Pinned by
`test_client_cannot_override_sector_identity`.

**2. Concurrency: no hand-rolled lock, deliberately.** Legacy took a single 30-second
global script lock that serialised *every* write in the app. SQLite has neither advisory
locks nor `SELECT ... FOR UPDATE`; it takes an exclusive write lock for the transaction's
duration, so saves are already serialised — and `UNIQUE (allocation_date, sector_id)` makes
a double-save impossible regardless, with the loser's `IntegrityError` translated to
`DATE_ALREADY_SAVED`. Implementing a fake lock would have been theatre. **Recorded in the
docstring: moving to PostgreSQL requires adding a per-date advisory lock**, since Postgres
permits concurrent writers that SQLite does not.

**3. Idempotency diverges from legacy, and the divergence is flagged.** Legacy stores only
`'1'` in its cache and answers a repeat with an *error*. CLAUDE.md rule 12 says a repeat
"returns the original result rather than double-writing", and `schema.sql` gives
`request_log` a `response_json` column for exactly that. Two project documents describe
replaying the result against one legacy behaviour that looks like an Apps Script cache
limitation. The response is stored so replay is possible, but **the current code still
raises `DUPLICATE_REQUEST` rather than replaying** — the stricter, legacy-matching
behaviour — and the whole conflict is written up at the top of
`repository/idempotency_repo.py` for a decision. Not resolved silently in either
direction.

## Errors / issues encountered

- None in the production code this time. One unused import (`audit_repo` in
  `allocation_service`) spotted and removed after the file grew.

## Achievements

**159 tests pass** (up from 146). The 13 new ones cover the properties that matter, not
just the happy path: an operator cannot save; a **denied admin** cannot save; a saved date
is immutable and the blocked attempt is audited; the same `request_id` cannot write twice;
the one enabled save rule (`REQUIRE_POSITIVE_ACQUIRED`); a failed save writes nothing; the
client cannot override sector identity; a short row count is rejected; the success audit
carries a correct snapshot; saved values carry into the next day; and 0.001 kg round-trips
to exactly 1 gram.

**Verified end to end against the real database, with the real 21 sectors:**
- Read `2026-09-21` — a **Monday** — and it correctly reported its rule source date as
  **Saturday 2026-09-19**. The six-day working week rule working on real data.
- Saved 21 allocation + 21 flow records; totals came out exactly
  (21 × 2.500 = 52.500 required, 21 × 1.250 = 26.250 alloted, 21 × 1.000 = 21.000 acquired).
- Re-read the following day and the carried previous requirement was **1.250 kg** — the
  prior row's closing balance.
- Confirmed the append-only trigger on real data: `DELETE FROM metal_allocation_audit_log`
  was **rejected by the database**, not merely by convention.

## Future things to implement / open questions

- **Smoke-test data is still in the database**: one saved day, `2026-09-21`, with 21+21
  synthetic rows (2.500/1.250/1.000 on every sector), one `request_log` row and one audit
  entry. Useful for exercising the UI next, but it is fabricated. The ledger rows can be
  deleted on request — **the audit entry cannot**, by design, which is itself a working
  demonstration of rule 13.
- **The revision path is not built yet** (`REVISE`, before/after snapshots, revision
  numbering, mandatory reason ≥10 chars). `assert_revision_reason()` and
  `get_latest_revision_number()` are ported and ready for it.
- Operator submission → staging is also still to do; `markStagingConsumed_` has no
  equivalent yet, so a save does not currently consume staged rows.
- The frontend still shows the placeholder dashboard — nothing yet renders this data.
- Unanswered: whether a duplicate `request_id` should replay the stored result (above),
  and the operator carry-forward asymmetry.
