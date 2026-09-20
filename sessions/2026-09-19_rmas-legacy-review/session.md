# Session: RMAS legacy review

Date: 2026-09-19

Goal: Complete the "First review" required by `CLAUDE.md` before any implementation —
understand the legacy Apps Script system, inventory all source files, identify
contradictions between `CLAUDE.md`/`FILE_SUMMARIES.md`/actual `.gs`/`.html` source, and
propose a Phase 1 plan. Explicitly: no files to be created, moved, renamed, deleted, or
modified, and no dependencies installed during this review.

## What happened

1. Read `CLAUDE.md` in full, then inventoried the project directory. Expected to find the
   12 `.gs` and 8 `.html` legacy files described in `FILE_SUMMARIES.md` — **none were
   present on disk.** Only `CLAUDE.md` and `FILE_SUMMARIES.md` existed at the project root;
   all `rmas/`/`frontend/src/` subdirectories were empty.
2. Investigated with `git status`/`git log` (environment metadata claimed this wasn't a git
   repo — it is; git worked fine). Found the actual repo history:
   - `52696da` (2026-09-18 18:55) — snapshot commit adding the 20 legacy `.gs`/`.html` files.
   - `5f89677` (2026-09-19 10:58, HEAD) — **"Port RMAS from Google Apps Script to Python
     (FastAPI) + JS, remove legacy source"** — deleted all 20 legacy files and added a
     complete 74-file Python/FastAPI + JS implementation (models, repository, routers,
     services, schemas, rules, one Alembic migration, tests, full `frontend/src/`) in a
     single commit.
   - On top of that HEAD commit, **all 89 of those files had been deleted from the working
     tree without being committed** — `git status` showed them all as unstaged deletions.
3. Recovered the 20 legacy files read-only from git history (`git show 52696da:<path>`) into
   scratch space, purely to complete the requested review. Did **not** restore anything into
   the actual working tree.
4. Spawned a background research agent to read all ~10,300 lines of recovered legacy source
   in full (all 12 `.gs` files, all 8 `.html` files) and report exact quotes for every
   business rule, toggle, and piece of critical logic — carry-forward rule, staging/save/
   revision workflow, scope/authorization, idempotency, concurrency lock, audit trail,
   sector/party/purity hardcoding check, the `RANGES` vs `EXPECTED` sector-count
   discrepancy, the `buildTag_Config_`/`checkInstalledFiles` duplicate-declaration bug, and
   HTML load order/IIFE structure.
5. Checked the already-installed `.metal` venv (Python 3.14.0): `fastapi 0.141.1`,
   `SQLAlchemy 2.0.54`, `alembic 1.20.0`, `psycopg 3.3.6`/`psycopg-binary`, `pydantic
   2.13.5`/`pydantic-settings`, `uvicorn`, `httpx`/`pytest 9.1.1`, `python-dotenv` — and also
   **`google-auth 2.58.0`**, which contradicts `CLAUDE.md`'s "no Google API dependency" rule
   and implies an undecided auth mechanism.
6. Peeked at the deleted port's `rmas/rules/business_rules.py` (from commit `5f89677`) for
   reference — found it had already correctly distinguished legacy toggles that are actually
   enforced by a conditional vs. merely declared-but-inert, with reasoning comments. Not
   boilerplate; a real prior design pass.
7. Delivered the full review in-conversation: system understanding, admin/operator workflow
   purpose, the six workflows (daily allocation, staging, revision, carry-forward, audit,
   reporting), file inventory, missing information, contradictions (both legacy-vs-`CLAUDE.md`
   and the repo-state issue), confirmed/unresolved/needs-confirmation split, legacy→new
   structure mapping table, Phase 1 plan (A–F), and a recommended-first-files table. Made no
   file changes.
8. Surfaced the repo-state issue as a blocking decision via a structured question rather than
   guessing. Options offered: restore everything from git, restore only the legacy files,
   leave the working tree as-is and have the user re-provide legacy files, or other.
   **User chose: leave the working tree as-is; they will re-provide the legacy `.gs`/`.html`
   files themselves.** No git restore performed.
9. Saved three entries to the assistant's persistent cross-session memory (separate from this
   log): the "never recover missing files from git history" rule, the current repo-state
   facts, and the user's review-first / long-uninterrupted-response working style.

## Errors / issues encountered

- The legacy-file extraction loop (`for f in $(git show 52696da --stat --name-only ...)`)
  also picked up stray words from the commit message/author line as bogus zero-byte
  filenames in scratch space (e.g. `Fri`, `18:55:03`, `<ShuGan@RC.local>`). Harmless —
  confined to scratch space, never touched the project — but `git show --name-only
  --format=` (empty format) would avoid the noise next time.
- Initially proceeded under the assumption this was a fresh, unimplemented project (per the
  task's framing); had to interrupt that assumption mid-review once the repo-state discovery
  came up, rather than silently reconciling "not yet implemented" with a repo that had
  already been fully ported once.

## Achievements

- A complete, source-verified architectural review now exists (in the conversation) with
  exact quotes for every confirmed business rule, several previously undocumented
  legacy-internal inconsistencies found beyond what `CLAUDE.md`/`FILE_SUMMARIES.md` already
  flagged (below), and a concrete Phase 1 scaffolding plan.
- Newly-found legacy inconsistencies not previously documented in `CLAUDE.md`/
  `FILE_SUMMARIES.md`:
  - `SAVED_DATE_IMMUTABLE_FOR_USERS`, `ALLOW_ZERO_PREVIOUS_REQUIREMENT`,
    `ALLOW_ZERO_CLOSING_BALANCE` are declared in `Config.gs` but never read/branched on by
    any function — inert/documentation-only, not enforced by a conditional.
  - `reviseDailyAllocation()` has no `request_id` cache-dedupe guard, unlike
    `saveDailyAllocation()`/`submitOperatorRequirements()` — revision idempotency relies only
    on the script lock + "date must exist" check.
  - The operator's own requirement screen (`getOperatorRequirementForDate()`) does **not**
    apply the `CARRY_FORWARD_FROM_LATEST_SAVED` fallback that the admin's Daily Allocation
    screen does — only the exact rule date is checked on the operator side.
  - `Config.gs`'s `OPERATOR_PARTIES`/`OPERATOR_FLOW_SECTORS` hardcode literal party names
    (`'Aalishaan'`, `'RC'`, `'Royal Chain'`) — a soft violation of legacy's own
    "sectors/parties are data" principle.
  - `DataService.gs` hardcodes the literal fallback purity label `'Any'`.
  - The version-check duplication is worse than documented: not just `buildTag_Config_()`
    declared twice (`'5C'` then `'5H'`, `'5H'` wins) — `checkInstalledFiles()` itself is a
    **duplicate global function**, once in `Config.gs` and once in `VersionCheck.gs` (with a
    stale `REQUIRED_BUILD = '5C'`), a genuine bug beyond a duplicated marker.
  - `Index.html` has a static `"19 sectors"` placeholder, independently confirming the
    19-vs-21 sector-count discrepancy is live, not just a stale comment.
  - The three "independent" client modules (`Scripts.html`/`Reports.html`/`Audit.html`)
    share no JS-variable state as documented, but `Reports.html` is what actually drives
    tab-switching (`switchView()`/`bind()`) for **all** views including the Daily view that
    `Scripts.html` owns — the module boundary isn't as clean at the DOM-event level as
    "share no state" implies.

## Future things to implement / open questions

Need user confirmation before implementation:
1. Authentication/identity mechanism for the new stack — `google-auth` is installed but
   `CLAUDE.md` forbids Google API dependencies; legacy identity came free from Google
   Workspace session binding, which has no direct equivalent yet.
2. Whether the three inert toggles (`SAVED_DATE_IMMUTABLE_FOR_USERS`,
   `ALLOW_ZERO_PREVIOUS_REQUIREMENT`, `ALLOW_ZERO_CLOSING_BALANCE`) should become real
   conditionals in the port or stay documentation-only constants (the deleted prior port
   chose the latter).
3. Whether revision should gain the cache-based idempotency guard save/submit have, or stay
   exactly as legacy.
4. Whether the operator-view carry-forward asymmetry should be replicated or unified.
5. Whether operator→party/flow-sector scope becomes a DB join table (proposed) instead of a
   hardcoded config mapping.
6. Whether the `'Any'` default purity literal is kept as-is or represented differently.
7. Whether any equivalent of `VersionCheck.gs`/duplicate `checkInstalledFiles()` is needed in
   the new stack at all (leaning: no).
8. The true allocation sector count (19 vs 21) and all real seed data (parties, sectors,
   purities, admin/operator identities) — none of the sandbox-looking data in `Config.gs`
   should be assumed real.
9. Whether `FILE_SUMMARIES.md` should move to `docs/FILE_SUMMARIES.md` to match `CLAUDE.md`
   §7, or `CLAUDE.md`'s path reference should be corrected instead.
10. Whether the Daily Allocation screen should stay one role-conditional view (mirroring
    legacy exactly) or split into two views ("allocation" and "staging") as `CLAUDE.md`'s
    `frontend/src/views/` listing might imply.

Next steps, once unblocked:
- **Blocked on the user placing the legacy `.gs`/`.html` files directly into the project
  directory** (the user declined any git-based restoration). Do not re-attempt git-history
  recovery.
- Once legacy files are in place: re-verify this review's findings against whatever the user
  actually adds (files may differ from the `52696da` snapshot), then get explicit answers to
  the 10 open questions above.
- Then proceed to Phase 1 scaffolding only, per the plan already presented: `rmas/config.py`,
  `rmas/database.py`, `rmas/main.py`, `rmas/schemas/common.py`, `rmas/rules/business_rules.py`
  (constants only), `requirements.txt`, `.env.example`, `.gitignore`, and a minimal
  `frontend/index.html` + `frontend/src/main.js` shell — no models, no migrations, no
  business logic yet, per `CLAUDE.md`'s Phase 1 constraints.
