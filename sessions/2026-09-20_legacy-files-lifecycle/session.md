# Session: Legacy files folder and three-stage lifecycle plan

Date: 2026-09-20

Goal: Create a dedicated folder for the user to paste the legacy `.gs`/`.html` source
files into (resolving the 2026-09-19 finding that no legacy files existed anywhere in the
working tree), and record the agreed three-stage plan for how those files coexist with,
then get replaced by, the new Python/JS port.

## What happened

1. Also mid-session, switched the project's development-history convention from a single
   rolling `WORK_LOG.md` to per-session folders under `sessions/` (per explicit user
   instruction), and updated `CLAUDE.md`'s log-keeping section accordingly. The
   now-redundant `WORK_LOG.md` was deleted; `sessions/2026-09-19_rmas-legacy-review/`
   holds the equivalent content from that session.
2. Created `legacy files/` at the project root — an empty folder for the user to copy the
   20 `.gs`/`.html` files into.
3. Added `legacy files/README.md` documenting the three-stage plan the user proposed:
   - **Stage 1 (now):** add legacy files to the working tree as reference-only material —
     not duplication, since the only other copy is inert git history.
   - **Stage 2 (during implementation):** each legacy file is read and ported to its
     mapped Python/JS equivalent (per `CLAUDE.md` §2's mapping table); legacy and new
     versions coexist during this window, which is expected, not a cleanup backlog.
   - **Stage 3 (after verification):** once a given legacy file's ported equivalent is
     implemented and verified to replicate its behaviour, that specific legacy file can be
     deleted — one file at a time as each is verified, never the whole folder at once.
4. Added a matching "Legacy source location and lifecycle" subsection to `CLAUDE.md` §7
   (Legacy Reference), so the convention lives in the project's own governing document,
   not just a folder-local README.

## Errors / issues encountered

None.

## Achievements

- `legacy files/` exists and is ready to receive the source the user will paste in.
- The three-stage lifecycle plan is now recorded in two durable places (`legacy
  files/README.md` and `CLAUDE.md` §7), not just this conversation.

## Future things to implement / open questions

- Waiting on the user to actually paste the 20 `.gs`/`.html` files into `legacy files/`.
- Once present: re-verify the 2026-09-19 review's findings against these actual files
  (they may differ from the git-history snapshot used for that review), then proceed to
  the Phase 1 scaffolding plan already agreed, subject to the 10 open questions logged in
  `sessions/2026-09-19_rmas-legacy-review/session.md`.
- As each legacy file is ported (Stage 2 → Stage 3), record the retirement of that file in
  the session log for whichever session does the verification, so the audit trail of
  "when was this legacy file confirmed replaced" is preserved.
