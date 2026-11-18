# Conventions for this repository

For developers and for AI coding agents (Claude Code reads this through `CLAUDE.md`; other
agents read `AGENTS.md` directly). How to build and where things are: `DEVELOPMENT.md`.

## Language
- Project language is English: docs, code comments, script output, commit messages.

## Workflow
- Read `docs/status.md` at the start of every session; update it at the end.
- Next steps and open questions are GitHub issues (`gh issue list`); close or add them as work
  is done or found.
- One commit per change with a clear message. Contributions as pull requests.
- Implement recurring tasks as scripts in `tools/`, usable without AI, documented in `tools/README.md`.

## Recomp rules
- Changes to the framework (segagenesisrecomp) only as a patch in `recomp/patches/NNNN-*.patch`
  (a stack, managed by `tools/recompiler_update.sh`); never commit the checkout directly.
- Take over interpreter evidence only via `tools/fold.sh` (validation + loss gate + deny list
  `recomp/game/ad_floor.deny.toml`); never edit `ad_floor.discovery.toml` by hand.
- Never delete evidence in `build/archiv/` and `build/recomp-*/evidence/` (local only, not in the repo).
- Headless runs, test routes and their pitfalls: `docs/notes/work-environment.md`.
- Before every headless run check that no other game instance runs, and protect the save file
  (same file).

## Documentation
- Docs hold facts, not history: state what is true now and replace what it supersedes. No session
  log, no "who played / whose idea / seen by" entries, no accounts of fixed bugs – keep only what a
  bug taught about the program. `docs/status.md` = what exists.
- Keep the docs small; update the topic file instead of appending dated entries.

## Findings
- Record every finding (address, routine, data format) immediately in `docs/notes/<topic>.md`.
- Always with evidence: emulator debugger, test run, diff. Mark anything unproven as **Hypothesis**.
- Addresses in the format `$01A3C4` (ROM) or `$FF1234` (RAM).

## Translation
- Target language: English.
- `translation/glossary.md` is binding; add new terms there first.
- The original Japanese text is kept next to the translation.
- Further languages (German `de`, French `fr`, Spanish `es`): `translation/<code>/*.toml`, translated from the English and keyed
  to the entries of `translation/script`; glossary `translation/glossary-<code>.md`.

## Never
- Never commit ROMs, save games or extracted assets (`.gitignore`).
- `config.env` contains local paths and is not committed.
