# Development

How the port is built, how it works and how to work on it. For playing, see `README.md`.

## How the port works

The game's 68000 code is translated to C ahead of time by the static recompiler
[segagenesisrecomp](https://github.com/mstan/segagenesisrecomp) and compiled into a native
program; the framework emulates the rest of the console (VDP, sound, Z80). Code the recompiler
did not find runs in its interpreter as a safety net, and every run writes evidence of it; that
evidence is turned into native functions with `tools/fold.sh`. In play nothing is interpreted
any more (`docs/notes/recompiler-runs.md`).

The translation is not a text patch on top: `tools/translate_rom.py` builds a translated ROM
(variant `tr`) from the Japanese one, with the five languages and the routines that switch them
(`docs/notes/translation-rom.md`). Game-specific additions (zoomed map, 16:9 frame, menu rows,
recording) are C hooks in `recomp/game/`; changes to the framework are a patch stack in
`recomp/patches/`. Players get a BPS patch with the release and supply their own ROM
(`docs/notes/release.md`).

## Requirements

- macOS on Apple silicon (the full toolchain), or Windows x64 with MSVC and Git Bash (builds and
  runs, but the translated ROM and the HD pack are made on the Mac: `docs/notes/windows.md`).
- cmake, ninja, SDL2, Python 3 and `uv` (Mac: `brew install cmake ninja sdl2 uv`).
- The Japanese ROM (Rev A, CRC32 `E0D5E18A`) – never commit it.
- [segagenesisrecomp](https://github.com/mstan/segagenesisrecomp) cloned recursively as the
  sibling folder `../segagenesisrecomp`; the pinned commit is `recomp/RECOMPILER_COMMIT`.

## Build and run

```sh
cp config.example.env config.env   # enter the ROM path; config.env is not committed
tools/recompiler_update.sh sync    # framework at the pin, patches applied
tools/build.sh --rom tr            # tr = the translated ROM, generated from the JP ROM
tools/run.sh --rom tr
```

Variants: `jp` (original), `en` (the Nebelwurfer English patch), `tr` (this translation; all
development happens here). Release packages: `tools/release.sh` (Mac app),
`tools/release_windows.sh` (Windows folder). All tools: `tools/README.md`.

## Where things are

| Path | Contents |
|---|---|
| `AGENTS.md` | conventions: language, commits, recomp rules, how findings are documented |
| `docs/status.md` | what exists now |
| `docs/notes/` | findings about the game and the port, one file per topic (index: `docs/notes/README.md`) |
| `tools/` | build, run, headless driver, translation, HD pack, release |
| `translation/` | script (Japanese next to each translation), glossaries, font tables |
| `recomp/` | recompiler config (`game/game.toml`), game hooks (`game/*.c`), framework patches |
| `release/` | launchers and READMEs of the Mac app and the Windows version |

## Working on it

- Open work is in the GitHub issues; `docs/status.md` says what exists.
- Every finding about the game (address, routine, data format) goes into its topic file in
  `docs/notes/`, with its evidence; unproven things are marked **Hypothesis**.
- The game can be driven headless through its debug server (`tools/drive.py`): routes to every
  screen, screenshots, RAM dumps (`docs/notes/work-environment.md`).
- Translations: `translation/glossary.md` is binding; German, French and Spanish are keyed to
  the English entries (`translation/glossary-<code>.md`).

### With an AI coding agent

The repository is set up for agents: `AGENTS.md` holds the rules (Claude Code reads it through
`CLAUDE.md`), `docs/notes/` the knowledge an agent needs to avoid rediscovering the game, and the
tools all run from the command line without a person at the window. Point the agent at
`AGENTS.md` and an issue.

## Contributing

Pull requests are welcome – one change per commit, English, and the rules in `AGENTS.md`. Never
include ROMs, save games, extracted game graphics or recordings.
