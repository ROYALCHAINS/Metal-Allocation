# Session: Operator staging path

Date: 2026-09-21

Goal:

1. Operators could not send metal requirements at all.
2. They should submit **Today's Required** (per allocation sector) and
   **Today's Acquired** (per Metal Flow party).
3. Once submitted it must not be editable again, and the submitted values must
   appear on the administrator's screen for that party.

## What happened

This was stage 1 of the two-stage workflow — deliberately dropped in the
restructure commit and never rebuilt. `POST /allocations/{date}` already refused
operators with *"Submit your requirement instead"*, but no such endpoint
existed, and the UI rendered a disabled "Administrator only" button.

Already in place and reused: the `metal_requirement_staging` table
(`submission_id`, `record_type`, `value_g`, status `SUBMITTED`/`CONSUMED`),
`scope_allows_party()` / `scope_allows_flow()`, and the three audit actions
`SUBMIT_REQUIREMENT` / `BLOCKED_RESUBMISSION` / `FAILED_SUBMISSION`, which the
CHECK constraint already permitted.

`StagingService.gs` (1098 lines) was read before writing anything, per rule 18.
That mattered — two rules would have been guessed wrong:

**The resubmission block is per (date × party), and ignores status.** Not per
user and not per sector. Two operators sharing a party block each other, because
the submission is made on the party's behalf. And it matches rows at **any**
status, so once the administrator commits and the rows flip to `CONSUMED`, the
party stays closed for that date. Filtering to `SUBMITTED` — the obvious
implementation — would quietly reopen submissions after every save, defeating
"a submission cannot be changed once sent".

**A staged zero still overlays the admin's screen.** Legacy guards with
`hasOwnProperty`, not truthiness: "this party needs nothing today" is a
statement, not an absence.

### Built

- `repository/staging_repo.py` — scope applied in the WHERE clause; a separate
  `any_rows_for_parties()` for the block check that deliberately does not filter
  status, with the reason in its docstring.
- `services/staging_service.py` — `submit_requirements()` in legacy's check
  order, plus `apply_staging_to_model()`, the overlay that carries an operator's
  figures onto the administrator's screen.
- `routers/staging.py` — `POST /staging/{date}`.
- `schemas/staging.py` — note `StagedAllocationInput` has **no** `alloted_kg`
  field. Allotment is the administrator's decision, and the shape makes that
  unrepresentable rather than merely unenforced.
- `allocation_service` gained `from_submission` on both row types and
  `already_submitted` / `staged_value_count` on the model; the save path now
  calls `staging_repo.mark_consumed()` after the masters are written, wrapped so
  a bookkeeping failure can never reverse a committed ledger.
- Frontend: `submitRequirements()` in `api/allocations.js`, and a role-swapped
  action button — Save for administrators, Submit Requirement for operators.
  The Required and Acquired inputs disable once `already_submitted` comes back
  true, and that flag is resolved on the server from the staging table.

Validation ported verbatim: `NO_ACQUIRED_METAL`, `NO_REQUIREMENT`,
`ADMIN_CANNOT_SUBMIT`, `NO_PARTY_ASSIGNED`, `NO_SECTORS`,
`SECTOR_NOT_IN_SCOPE`, `DATE_ALREADY_FINALISED`, `ALREADY_SUBMITTED`.
`REQUIRED_EXCEEDS_ACQUIRED` is implemented but dormant —
`OPERATOR_REQUIRED_WITHIN_ACQUIRED` is one of the deliberately-disabled toggles,
because demand legitimately exceeds supply and the shortfall carries forward.

## Errors / issues encountered

1. **`from rules import business_rules` was the wrong import form** — the
   module exports a dataclass *instance* of the same name. Caught by the tests.
2. **`db.rollback()` then reading `user.email`.** A rollback expires every ORM
   instance, so the failure-audit path re-queried a row inside a dead
   transaction and raised `ObjectDeletedError`. Fixed by capturing the email
   before the try block — right in production too, not just for the fixture.
3. **`from_submission` reached the dataclass but not the response schema**, so
   the field was simply absent from the JSON. Two tests caught it.
4. **`[hidden]` did not hide the button.** `.btn` sets `display:inline-flex`,
   which beats the user-agent `[hidden]` rule, so the "hidden" Save button stayed
   visible for operators. Added an explicit `[hidden]{display:none !important}`.
5. **The running server served stale code.** `python main.py` has no
   auto-reload, so the first live check returned a response with no `can_submit`
   field. Restarted it.

## Achievements

- 241 tests pass, up from 224. `tests/test_staging_submission.py` adds 17,
  pinning the one-shot rule (including that `CONSUMED` rows still block), that
  two operators on different parties can both submit for the same date, that a
  colleague on the *same* party cannot, the staged-zero overlay, and that an
  operator never sees another party's submission.
- Verified live against the running server: Snehal (operator, Royal Chain)
  submitted 10 sector figures and 1 Metal Flow figure — 10.500 kg required,
  12.000 kg acquired; a second attempt returned `ALREADY_SUBMITTED`; her screen
  locked; and the administrator's view of the same date showed
  `staged_value_count=11` with balances recomputed from the submitted
  requirement.
- All frontend modules pass `node --input-type=module --check`.

## Future things to implement / open questions

- **The admin has no banner announcing submissions.** Legacy shows
  *"N operator submission(s) loaded into this date"* on load. The count is in the
  payload (`staged_value_count`) but nothing surfaces it yet.
- **`submission_summary()` is queried but not returned.** The per-operator
  "who submitted, when" list is built in `apply_staging_to_model()` and dropped.
  It belongs on the admin screen next to the banner above.
- Three legacy read endpoints remain unported, none of which had a client caller:
  `getOperatorRequirementForDate`, `getCurrentUserScope`,
  `getStagedRequirementsForDate`.
- A blocked resubmission consumes its `request_id` for the idempotency window,
  matching legacy — so an immediate identical retry returns `DUPLICATE_REQUEST`
  rather than `ALREADY_SUBMITTED`. Faithful, but arguably confusing.
- Unchanged from earlier: audit timestamps are UTC while the app timezone is
  Asia/Kolkata; the fulfilment rate differs by design between Allocation History
  and the Dashboard; `summary.truncated` is still hard-coded false on both
  history pages; the revise path still has no idempotency guard.
