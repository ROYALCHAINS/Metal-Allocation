# Legacy Files — Purpose and Lifecycle

This folder holds the original Google Apps Script (`.gs`) and HTML (`.html`) source for
RMAS. It exists purely as **reference material** for the Python/JavaScript port —
nothing in the new application reads or runs anything from this folder.

## The three-stage plan

**Stage 1 — Now.** Add the legacy files back into the project directory (here). At this
point there is exactly one copy of each file in the working tree — this isn't
duplication, it's the first and only copy that actually exists on disk (the only other
copy lives in old git history, which is historical record-keeping, not something in
anyone's way).

**Stage 2 — During implementation.** Each legacy file gets read, understood, and ported
into its corresponding Python/JS file, per the mapping table in `CLAUDE.md` §2
("Legacy file mapping") — e.g. `Config.gs` → `rules/business_rules.py` + `config.py`,
`DateService.gs` → `services/date_service.py`, and so on. During this window, the legacy
file and its new equivalent genuinely coexist side by side — that's expected and fine.

**Stage 3 — After the port is verified working.** Once the Python/JS implementation is
confirmed to correctly replicate the legacy behavior it was ported from (see `CLAUDE.md`
§6 "Business-rule migration" test requirements), the corresponding legacy file has no
further purpose and can be deleted. Deletion happens file-by-file as each piece is
verified, not all at once — a legacy file whose Python/JS equivalent hasn't been
verified yet stays right where it is.

## Rules while files live here

- Do not move, rename, or modify any file in this folder — read-only reference.
- Do not delete a file here until its ported equivalent has been implemented **and**
  verified against it (see `CLAUDE.md` §6, item 18: "Read before writing. Consult the
  relevant legacy `.gs` file before changing ported behaviour").
- If a file expected here is missing, stop and ask — don't reconstruct it from git
  history or elsewhere (see project memory: `no-git-history-file-recovery`).
