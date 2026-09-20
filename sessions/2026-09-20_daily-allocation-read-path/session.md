# Session: Daily Allocation — read path (balance arithmetic + carry-forward model)

Date: 2026-09-20

Goal: Begin the Daily Allocation flow. Split deliberately into two verified stages:
**this session is the read path** (validation/arithmetic + the screen model with
carry-forward + `GET /allocations/{date}`); the save path follows.

Rationale for starting here rather than the dashboard: the dashboard is purely an
aggregation over `metal_master`/`metal_flow_master`, both of which are empty, so it would
render nothing. The allocation flow is what creates that data.

## What happened

Read the legacy source in full before writing anything (CLAUDE.md rule 18) —
`ValidationService.gs`'s `computeTotals_`/`assertSaveRules_`/weight assertions,
`DataService.gs`'s `buildAllocationModel_`, and `Code.gs`'s `saveDailyAllocation`.

### Implemented

- **`services/exceptions.py`** — domain exceptions carrying the legacy error codes
  verbatim (`INVALID_NUMBER`, `NEGATIVE_VALUE`, `DATE_ALREADY_SAVED`, …) so responses stay
  comparable with the Apps Script build. Services never import `HTTPException`.
- **`services/validation_service.py`** (extended from the normalisation-only partial port)
  — `assert_signed_weight()` / `assert_valid_weight()`, `compute_balance_g()`,
  `compute_totals()`, `assert_save_rules()`, `assert_revision_reason()`.
- **`repository/allocation_repo.py`, `repository/flow_repo.py`** — ledger reads/writes,
  including `latest_date_before()` (a plain indexed `MAX()`, since dates are TEXT
  `YYYY-MM-DD` and sort lexicographically).
- **`services/allocation_service.py`** — `build_allocation_model()`, porting
  `buildAllocationModel_()`.
- **`schemas/allocation.py`, `routers/allocations.py`** — `GET /allocations/{date}`,
  scoped to the caller, converting grams → kilograms at the boundary.

### Two judgement calls worth recording

**1. The 0.0005 epsilon must NOT be converted to "1 gram".** My first instinct was
`_EPSILON_G = kg_to_grams(EPSILON)` = 1, which would have been a real bug. Legacy asks
`abs(round3(a) - round3(b)) < 0.0005`; both operands are already 3-decimal values, so
their difference is a multiple of 0.001 — and 0.001 is *not* < 0.0005. The comparison
therefore only ever succeeds on identical values. In exact grams that is plain equality,
and treating a genuine 1-gram difference as "equal" would have been wrong. The epsilon
exists in legacy purely to absorb binary-float error, which integer grams do not have.
Caught before it was committed; the reasoning is in `nearly_equal_g()`'s docstring and
pinned by a test.

**2. Legacy rounds each total after summing; the port does not need to.** `computeTotals_`
calls `round3_()` on every total because float addition drifts. Integer sums are exact, so
no rounding is applied — the results are identical for any valid 3-decimal input, and the
difference is documented on `Totals`.

Also translated exactly: `BLOCK_OVER_ALLOCATION`'s `(alloted - acquired) > EPSILON`
becomes `alloted_g > acquired_g`, since in exact grams any positive difference is real.

## Errors / issues encountered

- One self-inflicted test bug: `test_totals_are_exact_over_many_rows` called a helper that
  does `db.query(Sector).one()` *after* the test had added 1000 sectors, so it raised
  `MultipleResultsFound`. Rewrote the test to build its rows directly. Production code was
  never at fault.

## Achievements

**146 tests pass** (up from 107). The new ones assert behaviour, not implementation:

- `test_allocation_model.py` (10) — **Monday looks back to Saturday**, with a Sunday row
  deliberately present to prove it is a real −2 and not merely "the most recent row";
  other days look back 1; previous requirement is the source row's **balance**, not its
  previous requirement; a skipped day falls back to the latest saved date and **reports
  the real source date**, not the theoretical rule date; no history gives zero; an unsaved
  day's balance equals what was carried in; a saved day reports its stored values; a
  **negative balance carries forward** (over-allocation is legitimate); flow carries
  previous acquired; and 1001 sectors × 1 gram totals exactly 1.001 kg.
- `test_balance_arithmetic.py` (29) — the balance equation across positive, negative and
  zero-closing cases; `0.1 + 0.2 - 0.3 == 0` exactly; signed weights allow negative while
  input weights do not; blanks are zero; commas stripped; garbage and floats refused; the
  `MAX_WEIGHT_KG` ceiling on both magnitude directions; totals and the zero-clamped
  "remaining"; that partial allocation, over-allocation and zero allotment are all
  **allowed** (the three disabled toggles); that those toggles genuinely fire when
  switched on (via monkeypatch, without enabling them in production); and the revision
  reason rules (mandatory, min 10, truncated at 1000).

Endpoint verified live against the running server: `GET /allocations/{date}` returns 401
unauthenticated, and the auth gate runs before date parsing so nothing leaks to an
anonymous caller.

## Future things to implement / open questions

**Next: the save path** — `POST /allocations`, which needs:
- `repository/audit_repo.py` + `services/audit_service.py` (append-only writes, snapshot
  builders, `getLatestRevisionNumber_`)
- `repository/idempotency_repo.py` — the `request_log` table, 900s window
- Per-date locking (`SELECT … FOR UPDATE` / advisory lock — a deliberate improvement on
  legacy's global 30s script lock, which serialised *all* writes)
- `validate_and_normalize_payload()` — rebuild rows from live sector definitions and index
  submitted rows by normalised sector key, so **row order can never corrupt a save** and
  party/sector/purity/priority always come from the database, never the client
- The ordering legacy uses: idempotency check → admin check → validate → acquire lock →
  **re-check the date after the lock** → write both ledgers → mark staging consumed
  (never fatal) → audit

Still unanswered from earlier: the revise idempotency gap and the operator carry-forward
asymmetry — both become relevant in the save/revise work.
