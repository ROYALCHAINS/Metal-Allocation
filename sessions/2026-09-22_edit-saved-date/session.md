# Session: Edit Saved Date — admin revision with forward cascade

Date: 2026-09-22

Goal: Implement `PROMPT_edit_saved_date.md` — the administrator revision workflow, plus a
**forward cascade** that recomputes `previous_requirement` and `balance` on every later saved
date, one audit entry per recalculated date linked to its parent, and clearer Action labels.

## What happened

### The starting position

The revision path did not exist in the port at all. Everything around it did, unused:
`allow_admin_revision` had **zero readers**, `assert_revision_reason` was implemented and
tested but **never called**, `get_latest_revision_number` had **zero callers**, and
`delete_rows_for_date` sat in both ledger repos docstringed *"Used by the revision path"* as
dead code. The modal CSS was fully ported and unused, as was `.btn--gold`.

Three findings shaped the design, all confirmed in the source:

1. **The source-date rule was split across two files.** `date_service` had only the
   Monday→Saturday calendar rule; the `CARRY_FORWARD_FROM_LATEST_SAVED` fallback lived in a
   **private** function inside `allocation_service`. The spec demands one implementation
   shared by the screen and the cascade — there wasn't one.
2. **`previous_requirement` was client-supplied and trusted** on the *existing save path*.
   Read-only on screen, but the server persisted whatever the request carried.
3. **Audit IDs could collide inside a cascade.** Four decimal digits over a one-second stamp
   is 9000 values: ~4.7% collision at 30 entries, ~18% at 60. `audit_id` is UNIQUE, so one
   collision would abort the whole transaction — ledger included.

### How the split rule was resolved

`date_service.resolve_source_date` now takes **injected lookups** rather than a `Session`:
the screen passes repository-backed lambdas, the cascade passes set-backed ones. The same
function object called twice — genuinely one implementation, not two kept in step by
discipline — and `date_service` stays free of any persistence dependency, which is what lets
`cascade_service` be pure.

Two subtleties preserved exactly, each with its own test: the rule resolves **per ledger**
(allocation and flow can land on different dates), and the fallback searches before
**`selected`**, not before the rule date — so it can return a date *later* than the rule date
(Monday whose Saturday is empty but whose Sunday was saved sources from Sunday).

### The cascade

`services/cascade_service.py` is pure — no `Session`, no ORM, no `Decimal`, integer grams
throughout. It walks later dates ascending, tracks a `dirty` set, and skips any date whose
source date did not move.

**Propagate-only, on purpose.** A revision must not quietly repair drift it did not cause:
the audit trail would claim credit for unrelated corrections, and a deliberate manual
adjustment would be overwritten with nobody asked. A `propagate_only=False` mode exists so
the reconciliation report reuses **the same function** rather than reimplementing the rule.

### Write strategy — asymmetric, and documented as such

Cascaded dates are **updated in place**: the cascade changes exactly two figures, and
`priority_snapshot`/`purity_snapshot` record what applied *on that date*. A delete-and-insert
would have to reconstruct them and is one careless line from substituting today's sector
definitions into a historical record. It also sidesteps the ordering hazard entirely — both
write helpers only `flush()`, so insert-before-delete trips the unique constraint.

The **edited date** is delete-then-insert, because its sector set can legitimately differ
from what was saved (the payload is rebuilt from live definitions). That finally gave
`delete_rows_for_date` its caller.

### Atomicity

`audit_service.write_entry` only flushes, so the edited date, every cascaded date and all
their audit entries commit at **one `db.commit()`**. The ledger can never be left
half-cascaded and the log can never record a cascade that did not happen — which replaces
legacy's delete-then-restore dance that could itself fail and leave `REVISION_RESTORE_FAILED`
behind.

### Audit IDs

Widened to `secrets.token_hex(4)` — 4.29e9 values, taking 60 entries in one second to ~4e-7 —
plus `generate_audit_ids(n)`, which pre-allocates mutually-distinct ids before the first
write. That makes the one collision class under our control impossible rather than merely
unlikely, and hands the failure branch its parent id.

### Migration 0005

One hand-rolled table rebuild, modelled on 0004. `parent_audit_id` alone could have been
`add_column`, but admitting `RECALCULATE` means altering a CHECK, which SQLite cannot do in
place. **Not `batch_alter_table`** — `env.py` sets `render_as_batch` for SQLite so
autogenerate would suggest it, and batch rebuilds the table *without recreating the triggers*,
silently discarding the append-only guarantee. The triggers are dropped and recreated by hand.

`downgrade()` refuses while any `RECALCULATE` row exists: they cannot become `REVISE` (that
would retroactively inflate the Revisions KPI) and cannot be deleted (append-only, in both
directions), so it stops and asks.

## Errors / issues encountered

- **Two shell heredocs failed** — the revision service and the routes were too long for the
  Bash tool's argument limit (one produced `ENAMETOOLONG`). Written to scratchpad files and
  appended instead.
- **`snapshot_allocations` needs sector name, priority and purity**, none of which the
  cascade's `LedgerRow` carries and only two of which the ORM row carries. Added explicit
  snapshot adapters rather than teaching the snapshot about two more shapes — and the
  recalculated snapshot takes priority/purity from the *stored* row, since substituting
  today's definitions into a historical record would be quietly wrong.
- **Three test bugs, all mine, all instructive:** September has 30 days, so a parametrised
  case built `2026-09-31`; the row-count rule requires *every* defined sector in the payload,
  so the helpers had to default unnamed sectors to zero; and the spec's worked example
  assumes Saturday carries 10.000 from *its* source date, which I had not seeded — the server
  correctly derived 0 and the test caught my omission rather than a defect.
- **One test asserted the wrong behaviour.** With carry-forward disabled at a gap there is no
  source date, so under propagate-only the chain simply stops. I had asserted a
  recalculation. The code was right; the assertion was rewritten to say what actually
  happens, and a second test covers the full-recompute path.

## Achievements

- **The revision path exists**, with legacy's guard order intact and every failure audited.
- **The forward cascade works at real scale**: on a copy of the live database, editing the
  earliest of 19 saved dates recalculated **18 later dates across 21 sectors in 0.14s**, as
  one transaction.
- **The spec's worked example reproduces exactly**, both as a pure unit test and end to end
  through the service: Monday's Prev. Req. 3.000 → 7.000, Tuesday's 5.000 → 9.000, and
  Saturday's own Prev. Req. unchanged at 10.000 — which is precisely why the cascade entries
  are what make a Prev. Req. change visible in the audit log at all.
- **The headline invariant proven on real data**: after a cascade, the Daily Allocation screen
  and the ledger were compared across **399 rows over 19 dates — zero mismatches**, and the
  balance formula held on every row.
- **The spec's actual outcome demonstrated over HTTP**: opening a cascade entry's *View
  changes* now shows a Prev. Req. difference — `1.250 → 0.250` on 15 rows. The spec was right
  that the UI was already capable; what was missing was the data.
- **Guards verified end to end**: preview reported *"This revision will recalculate 17 later
  saved dates across 15 sectors"*; an operator got **403** and the attempt was recorded as
  `UNAUTHORIZED_REVISION`; the Revisions KPI counted **1** with 17 cascade entries present.
- **Two live holes closed.** `previous_requirement` is now derived on **both** the save and
  revise paths, so a crafted request cannot set it. And the save path's
  `except RmasError: raise` — which let a validation failure escape with **no audit row and no
  rollback**, contradicting rule 14 — now audits every failure.
- **The reconciliation report found real drift in the live ledger**: 56 differing figures
  across 2 dates and 14 sectors, of 19 examined. It changed nothing.
- **270 → 308 tests passing**, including 17 pure cascade tests and 20 revision tests covering
  atomicity (a mid-cascade failure leaves ledger *and* log untouched), the guards, the KPI,
  parent/child linkage, and preview-matches-commit.

### Decisions taken this session

1. `REVISE` displays as **"Edited saved data"**; the stored value never changes.
2. Cascade entries are `RECALCULATE`, displayed **"Recalculated from revision"**, with the
   neutral badge — a consequence, not another administrator edit.
3. Reconciliation script: **report only**, no `--fix` flag at all.
4. `previous_requirement` derived on **both** paths, not just revise.
5. Cascaded dates **updated in place**; only the edited date is replaced.
6. Delivered as staged work, server first.
7. The save path's missing-audit bug **fixed too**.
8. Cascade is **propagate-only**.
9. A cascaded date's banner gets its own line rather than claiming it was "revised".

## Future things to implement / open questions

- **Decision 9 is not yet built.** `get_date_revision_summary` still partitions on literal
  `== REVISE` / `== SAVE`, so a cascaded date's Daily Allocation banner says nothing about
  having been recalculated even though its figures changed and its revision number went up.
  The rest of the feature does not depend on it.
- **The drift the report found needs a human decision** — 2 dates, 14 sectors. Some may be
  deliberate manual adjustments; the script deliberately cannot tell.
- **`previous_requirement_kg` is accepted-and-ignored**, not removed, so a browser tab loaded
  before this change still posts successfully. Delete the field once the frontend has shipped.
- **Idempotency errors rather than replaying**, still contradicting `idempotency_repo`'s own
  docstring and rule 12. Matched the code; did not resolve it inside this feature.
- **`LockTimeoutError` / `LOCK_TIMEOUT_MS` remain orphans.** On SQLite the range lock the spec
  asks for exists implicitly — the engine serialises all writers — and cannot be made
  explicit. Noted in the service: the unique constraint does **not** protect a
  delete-then-reinsert the way it protects an insert; that protection is the write lock alone.
  A Postgres move wants one advisory lock on a constant ledger key, not one per date, since an
  unbounded per-date lock set invites deadlock.
- **Audit ID format widened** from legacy's four digits to eight hex. A deliberate departure.
- **Not seen in a browser.** The revise button, revision mode, the reason modal and the
  parent/child links in the audit detail are all verified only by syntax check and by their
  server-side counterparts. Dark-mode contrast for `.btn--link` inside `.snapshot-note` has no
  rule in `theme.css` and is the most likely thing to look wrong.
