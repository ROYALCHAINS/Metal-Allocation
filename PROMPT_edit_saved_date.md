# Build Prompt — Edit Saved Date (Admin Revision with Forward Cascade)

Paste the section below into a chat with the RMAS source attached. The current
behaviour was read from `Code.gs`, `DataService.gs`, `ValidationService.gs`,
`Scripts.html` and `Audit.html`. What is new is marked as new.

---

## Read this first — three facts that shape the request

**1. Editing a saved date already exists.** `reviseDailyAllocation()` in
`Code.gs` is live, `RULES.ALLOW_ADMIN_REVISION` is `true`, and the audit diff
table already has *Prev. Req. (before)* and *Prev. Req. (after)* columns. This
is an **enhancement**, not a new feature.

**2. Revisions do not cascade today — and that is a real gap in the live data.**
`reviseDailyAllocation()` deletes and rewrites **only the selected date**. Every
later saved date keeps the `previousRequirement` it was saved with, which was
carried forward from the *old* balance. After any revision, later saved dates are
silently stale. `buildAllocationModel_()` confirms it: for a saved date it reads
`saved.previousRequirement` from storage and never recomputes it. Any revision
already made in production has left this inconsistency behind.

**3. On the edited date itself, Prev. Req. before and after will be identical.**
A date's previous requirement comes from its *source* date — the one before it —
which the admin did not touch. It is also read-only in the UI (`Scripts.html`
renders it as `.readonly-value`). So Prev. Req. only changes on the **later**
dates the cascade recalculates. For the audit log to show a Prev. Req. change,
**each cascaded date needs its own audit entry**. That is the core of this design.

---

## PROMPT

> Enhance the **administrator revision** ("Edit Saved Date") workflow in the Royal
> Metal Allocation System, ported to Python (FastAPI) + JavaScript. Three changes:
>
> 1. When an admin edits a saved date, **recalculate balance on that date and
>    carry the change forward through every later saved date** for the affected
>    sectors.
> 2. **Record every recalculated date in the audit log** with before/after
>    snapshots, so *Prev. Req. (before)* and *Prev. Req. (after)* show the change
>    in the **View changes** detail.
> 3. Display revision entries in the Audit Log **Action** column as
>    **"Previously edited data"**.
>
> **The UI and CSS must stay visually identical** — reuse existing class names and
> markup. Where a new visual element is needed, propose it before building it.
>
> ---
>
> ### Current workflow — preserve it
>
> The revision is triggered from the **Daily Allocation** view, not the Analysis
> Dashboard:
>
> 1. Admin selects a date that is already saved. The screen loads read-only.
> 2. `#btnAdminRevise` is visible only when `model.canRevise` is true.
> 3. `requestRevision()` unlocks the Today's Required, Acquired and Alloted fields,
>    sets header status to *"Revision mode"*, shows the warn banner *"Revision
>    mode. Edit the values, then use Submit Revision. All changes are audited."*,
>    and relabels `#btnSave` to **"Submit Revision"** with `data-mode="revise"`.
> 4. `requestRevisionSubmit()` opens `#modal` with `requireReason: true`. The
>    reason must be **at least 10 characters**, else `#modalReasonError` shows
>    *"The revision reason must be at least 10 characters."*
> 5. `doRevise(reason)` calls the revision endpoint.
>
> Server side, keep every existing guard in this order:
>
> - `RULES.ALLOW_ADMIN_REVISION` off → `REVISION_DISABLED`
> - Not an admin → write an `UNAUTHORIZED_REVISION` / `BLOCKED` audit entry, return
>   `NOT_AUTHORIZED`. **The UI flag is never trusted.**
> - `assertRevisionReason_()` — minimum 10 characters
> - `validateAndNormalizePayload_()` and `assertSaveRules_()`
> - Lock, then `DATE_NOT_SAVED` if the date has no rows
> - `revisionNumber = latest for this date + 1`
> - Any failure → `FAILED_REVISION` / `FAILED` audit entry
>
> Do **not** re-enable any disabled rule toggle as part of this work.
> `REQUIRE_FULL_ALLOCATION`, `REQUIRE_POSITIVE_ALLOTED`, `BLOCK_OVER_ALLOCATION`
> and `OPERATOR_REQUIRED_WITHIN_ACQUIRED` stay `False`.
>
> ---
>
> ### Change 1 — Balance calculation on the edited date
>
> The formula is unchanged:
>
> ```
> balance = previousRequirement + todayRequired - alloted
> ```
>
> **The server must derive `previousRequirement` itself.** Today
> `validateAndNormalizePayload_()` accepts it from the client payload via
> `assertSignedWeight_(submitted.previousRequirement, ...)`. It is read-only in the
> UI, but a crafted request could still send any value. For the edited date,
> recompute it from the source date using the carry-forward rule below and ignore
> whatever the client sends.
>
> The admin may edit **Today's Required**, **Alloted** and **Acquired**. Balance is
> always computed, never accepted.
>
> ---
>
> ### Change 2 — Forward cascade (NEW)
>
> After the edited date is rewritten, walk forward through every **later saved
> date** and recompute each one's `previousRequirement` and `balance`.
>
> **The cascade must use exactly the same source-date rule as
> `buildAllocationModel_()`**, or the recalculated values will disagree with what
> the Daily Allocation screen shows. That rule:
>
> ```
> rule_date(D)   = D - 2 days   if D is a Monday   (Monday looks back to Saturday)
>                = D - 1 day    otherwise
>
> source_date(D) = rule_date(D)                       if rule_date(D) has saved rows
>                = latest saved date strictly before D if CARRY_FORWARD_FROM_LATEST_SAVED
>                = none                               otherwise
> ```
>
> **Source date is resolved per date, not per sector.** Then, per sector:
>
> ```
> previousRequirement(D, S) = balance(source_date(D), S)   if S has a row on source_date(D)
>                           = 0                            otherwise
> balance(D, S)             = previousRequirement(D, S) + todayRequired(D, S) - alloted(D, S)
> ```
>
> Note the zero case: a sector absent from its source date carries **0**, not the
> value from some earlier date. Replicate this exactly.
>
> **What the cascade changes and what it never touches:**
>
> | Field on a later date | Cascade behaviour |
> |---|---|
> | `previousRequirement` | **recomputed** |
> | `balance` | **recomputed** |
> | `todayRequired` | never changed |
> | `alloted` | never changed |
> | `acquired` (Metal Flow) | never changed |
> | priority / purity snapshots | never changed |
>
> Metal Flow Master has no balance column, so **the cascade touches Metal Master
> only**.
>
> **Scope of the cascade.** Each sector's chain is independent. Only sectors whose
> balance on the edited date actually changed need walking forward. Process dates
> in ascending order, since each date depends on the one before it.
>
> *Optional optimisation:* once a sector's recomputed balance on some date equals
> its stored balance (compared with the epsilon below), later dates for that sector
> cannot change and its chain may stop. Implement correctness first.
>
> **Unsaved future dates need nothing.** A date that has never been saved computes
> `previousRequirement` live when loaded, so it picks up the new balance
> automatically.
>
> **Compare with epsilon, never `==`.** Use `EPSILON = 0.0005`. With integer-gram
> storage this reduces to exact integer equality — but if any value passes through
> `Decimal` kilograms, use the epsilon.
>
> **Negative balances are permitted.** A cascade may drive a later balance below
> zero. `BLOCK_OVER_ALLOCATION` is `False` and signed weights are allowed, so do
> **not** block the revision. Do report it in the preview (below).
>
> **Revision numbers.** Every date whose stored rows change gets its own
> `revision_number` incremented — its stored data has changed, so it is revised.
>
> #### Worked example — one sector, three saved dates
>
> Before the revision:
>
> | Date | Prev. Req. | Today's Req. | Alloted | Balance |
> |---|---|---|---|---|
> | Sat | 10.000 | 5.000 | 12.000 | **3.000** |
> | Mon (source: Sat) | 3.000 | 4.000 | 2.000 | **5.000** |
> | Tue (source: Mon) | 5.000 | 1.000 | 6.000 | **0.000** |
>
> Admin edits **Saturday**, changing Alloted from 12.000 to 8.000.
>
> After the revision and cascade:
>
> | Date | Prev. Req. | Today's Req. | Alloted | Balance | Audit action |
> |---|---|---|---|---|---|
> | Sat | 10.000 *(unchanged)* | 5.000 | **8.000** | **7.000** | `REVISE` |
> | Mon | **7.000** | 4.000 | 2.000 | **9.000** | cascade entry |
> | Tue | **9.000** | 1.000 | 6.000 | **4.000** | cascade entry |
>
> Saturday's Prev. Req. is identical before and after. The Prev. Req. change
> appears on **Monday (3 → 7)** and **Tuesday (5 → 9)** — which is why those dates
> need their own audit entries.
>
> ---
>
> ### Change 3 — Atomicity and locking
>
> The edited date **and every cascaded date** commit in **one transaction**. Either
> all of them change or none do. Never leave the ledger half-cascaded.
>
> The legacy system used delete-then-append with a hand-written restore on failure,
> and could reach a state where the restore itself failed
> (`REVISION_RESTORE_FAILED`). A database transaction replaces all of that.
>
> Lock the range **from the edited date to the latest saved date**, not only the
> edited date. A concurrent save on a later date during the cascade would otherwise
> read a balance that is about to change.
>
> ---
>
> ### Change 4 — Audit log entries
>
> One revision now produces **one parent entry plus one entry per cascaded date**.
>
> **Parent entry** — the date the admin edited:
>
> | Field | Value |
> |---|---|
> | `action_type` | `REVISE` *(unchanged stored value)* |
> | `action_status` | `SUCCESS` |
> | `revision_reason` | the admin's reason |
> | snapshots | full before/after allocation and flow for that date |
> | `request_id` | from the client |
>
> **Cascade entries** — one per later date that changed (NEW):
>
> | Field | Value |
> |---|---|
> | `action_type` | a new value, e.g. `RECALCULATE` — **needs your confirmation** |
> | `action_status` | `SUCCESS` |
> | `revision_reason` | generated: *"Recalculated after revision of <edited date>"* |
> | snapshots | before/after **allocation** for that date. Flow unchanged, so omit flow snapshots or write identical ones — pick one and be consistent |
> | `request_id` | **the parent's request ID** |
> | `parent_audit_id` | **new column** — the parent entry's `audit_id` |
>
> Schema changes this requires in `metal_allocation_audit_log`:
>
> - add `parent_audit_id TEXT REFERENCES metal_allocation_audit_log(audit_id)`
> - add the new action value to the `action_type` CHECK constraint
> - add `CREATE INDEX idx_audit_parent ON metal_allocation_audit_log(parent_audit_id)`
>
> The audit log stays **append-only**. The existing triggers blocking UPDATE and
> DELETE remain.
>
> Write all audit entries **inside the same transaction** as the ledger changes, so
> the audit never records a cascade that did not happen.
>
> **The Revisions KPI** (`counts.revisions`) currently counts
> `actionType === 'REVISE'`. Keep it that way — cascade entries are consequences,
> not administrator edits, and must not inflate the count.
>
> ---
>
> ### Change 5 — View changes shows Prev. Req. before/after
>
> **No change to the diff table is needed.** `allocationDiffTable()` in
> `Audit.html` already renders nine columns including *Prev. Req. (before)* and
> *Prev. Req. (after)*, and `diffAllocationSnapshots_()` already compares
> `previousRequirement`, applying `.is-changed` when the values differ beyond
> epsilon.
>
> What was missing is the **data**: without cascade entries, no entry ever had a
> differing Prev. Req. With them, opening **View changes** on a cascade entry shows
> the Prev. Req. cell highlighted in the changed colour `#fdf0d8`.
>
> Additions to the detail modal (`renderDetail()`):
>
> - **Parent entry:** a line under the meta grid — *"This revision recalculated N
>   later date(s)."* — listing each cascaded date with its audit ID as a link that
>   opens that entry's detail.
> - **Cascade entry:** a meta item *"Triggered by"* showing the parent audit ID as a
>   link back to it.
>
> These are new visual elements. **Propose the markup and styling before building
> them**, using existing classes (`.detail-meta__item`, `.audit-id`,
> `.snapshot-note`) where they fit.
>
> ---
>
> ### Change 6 — Action column label "Previously edited data"
>
> **Change the display label only. Do not change the stored value.**
>
> The stored `action_type` stays `REVISE`. Changing it would break the Action Type
> filter, the Revisions KPI, the schema CHECK constraint, and every historical
> entry already recorded as `REVISE`.
>
> Today `actionBadge()` derives the label by replacing underscores:
> `String(action).replace(/_/g, ' ')`, so `REVISE` renders as "REVISE". Replace
> that with an explicit label map:
>
> ```javascript
> const ACTION_LABELS = {
>   SAVE:                  'SAVE',
>   REVISE:                'Previously edited data',
>   RECALCULATE:           '<label to confirm>',
>   BLOCKED_DUPLICATE:     'BLOCKED DUPLICATE',
>   FAILED_SAVE:           'FAILED SAVE',
>   FAILED_REVISION:       'FAILED REVISION',
>   UNAUTHORIZED_REVISION: 'UNAUTHORIZED REVISION'
> };
> ```
>
> Unlisted actions fall back to the underscore replacement. The **CSS class** still
> comes from the existing map — `REVISE` keeps `audit-badge--revise` (gold).
>
> Apply the same label in three places:
>
> 1. The **Action** column of the audit table
> 2. The **Action** item in the detail modal's meta grid
> 3. The **Action Type** filter dropdown — show the label, **send the stored
>    value**. `fillSelect()` currently uses the raw value as both.
>
> The **CSV export** should carry the stored value, not the label, so exports stay
> machine-readable.
>
> ---
>
> ### Change 7 — Cascade preview before confirming (recommended)
>
> An admin editing a date three months back could rewrite dozens of later dates.
> They should see that before confirming.
>
> Add a preview endpoint that runs the cascade **without committing** and returns:
>
> - number of later dates that will change
> - number of sectors affected
> - any later date whose balance will turn negative
>
> Show it in the existing `#modal` body in `requestRevisionSubmit()`, alongside the
> current totals line. Example:
>
> > *This revision will recalculate 14 later saved dates across 3 sectors.
> > 2 dates will end with a negative balance.*
>
> This is a UI change — **propose the wording and layout before building it.**
>
> ---
>
> ### Endpoints
>
> `POST /api/allocations/{date}/revise` — request: `todayRequired`, `alloted`,
> `acquired` per sector, `revisionReason`, `requestId`. **No `previousRequirement`
> and no `balance` accepted.** Response adds `cascadedDates[]` and
> `cascadeAuditIds[]`.
>
> `POST /api/allocations/{date}/revise/preview` — same request, no commit. Returns
> the cascade summary.
>
> ---
>
> ### Where it goes in the port
>
> | Concern | Location |
> |---|---|
> | Revise endpoint, preview endpoint | `routers/allocations.py` |
> | Revision orchestration and transaction | `services/allocation_service.py` |
> | Cascade computation | `services/cascade_service.py` — **pure function**, no DB access, so it can be tested in isolation |
> | Source-date rule | `services/date_service.py` — **one implementation**, shared by the screen model and the cascade |
> | Reading and writing ledger rows | `repository/allocation_repo.py` |
> | Audit writes | `services/audit_service.py` → `repository/audit_repo.py` |
> | Action label map | `frontend/src/lib/` — one module, imported by the table, the modal and the filter |
>
> **The source-date rule must have exactly one implementation.** If the screen
> model and the cascade each carry their own copy, they will drift, and the screen
> will show different numbers from the ledger.
>
> ---
>
> ### Tests that must exist
>
> 1. The worked example above, exactly.
> 2. **Monday edit** — the following Tuesday sources from Monday; Monday itself
>    sources from Saturday.
> 3. **Gap in saved dates** — a later date whose rule date was never saved falls
>    back to the latest saved date before it.
> 4. **Sector absent on source date** carries 0.
> 5. **Balance turning negative** is allowed and reported in the preview.
> 6. **Two sectors, one edited** — the untouched sector's later rows are unchanged
>    and produce no cascade audit entries.
> 7. **Failure mid-cascade** rolls back every date and every audit entry.
> 8. **Non-admin** is refused and an `UNAUTHORIZED_REVISION` entry is written.
> 9. **A client-supplied `previousRequirement` is ignored.**
> 10. **Editing the latest saved date** cascades nothing and produces one entry.
> 11. The Revisions KPI counts the parent only.
>
> ---
>
> ### Rules that must hold
>
> 1. The server derives `previousRequirement` and `balance`; it accepts neither.
> 2. The cascade uses the **same** source-date rule as the screen model — one
>    implementation.
> 3. The cascade changes only `previousRequirement` and `balance` on later dates.
> 4. The edited date and all cascaded dates commit atomically, with their audit
>    entries, or not at all.
> 5. The stored `action_type` stays `REVISE`; only the displayed label changes.
> 6. Every cascaded date gets its own append-only audit entry linked to the parent.
> 7. Negative balances are allowed, never blocked.
> 8. No disabled rule toggle is re-enabled.
> 9. Weights are integer grams in storage, `Decimal` at the boundary, never
>    `float`.

---

## Notes for you, not part of the prompt

**Your existing data is probably already inconsistent.** Because the legacy system
never cascaded, every revision ever made has left later saved dates carrying a
`previousRequirement` based on the old balance. Before or during the port, run a
one-off reconciliation: replay the cascade across the whole ledger from the
earliest date and report every row whose stored value differs from the recomputed
one. **Report first, don't auto-fix** — some of those differences may be
deliberate manual adjustments.

**Two decisions I need from you:**

1. **The label for cascade entries.** You specified "Previously edited data" for
   the admin's edit. The recalculated later dates need something distinct, or the
   log will make it look as if the admin edited every one of them by hand. Options:
   *"Recalculated from revision"*, *"Auto-recalculated"*, *"Carried forward
   update"*.
2. **Whether "Previously edited data" is the exact wording you want.** Read in the
   Action column it could suggest the row *is* old data, rather than that it
   *records an edit to* previously saved data. Something like *"Edited saved
   data"* may read more clearly. Your call — the prompt uses your wording as given.

**Also worth knowing:** the client-supplied `previousRequirement` is a live gap
today, not just a porting concern. The field is read-only on screen, but the
server trusts whatever the request carries. It is fixed by the port as specified,
but it is also a small, safe fix to the Apps Script version if you want it closed
sooner.
