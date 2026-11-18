# Tools

## build.sh / run.sh

Build and start the game, with ROM variant `jp` (original), `en` (Nebelwurfer patch) or `tr`
(our translation, generated from `jp`, see translate_rom.py below).
Reads `ROM_JP_PATH`, `ROM_EN_PATH`, `ROM_VARIANT` (default) and `RECOMPILER_DIR` from `config.env`.
Needs cmake, ninja, sdl2 (`brew install cmake ninja sdl2 uv`). The ROM selection lives in `tools/rom_select.sh`.
On Windows both run in Git Bash through `tools\win` (below); tr there uses the `build/rom/ad-tr.md`
made on the Mac when `swift` is missing.

| Call | Effect |
|---|---|
| `tools/build.sh [--rom jp\|en\|tr]` | check the ROM via SHA-256, apply framework patches, generate C code, build `build/recomp-<variant>/ADRecomp` |
| `tools/build.sh --rom en --clean` | the same with an empty build folder (save games `*.srm` and save states are kept) |
| `tools/run.sh [--rom jp\|en\|tr] [--ramlog] [--no-hd] [--no-wide] [ARGS]` | start the game; with the HD pack the frame is 16:9 (side margins of 39 px, `GENESIS_HD_MARGIN`; the zoomed-out map fills them, other screens show the camouflage frame, `AD_FRAME=0` = black, `docs/notes/frame.md`; `--no-wide` = 320x224 as before, `docs/notes/map.md`); ARGS go to the runner; output also to `run.log`; evidence per session in `evidence/<time>/`; loads the HD pack `build/hd/pack.bin` when present (`--no-hd`: original graphics; F10 in the game toggles; F9 = zoomed-out map, half-size hexes, menus moved off the cursor, on by default and kept in `ad-port.ini`, `AD_MAP_ZOOM=0|1` overrides it for one launch; also System menu → System → "HD map") |

Save games (battery SRAM) are stored as `<ROM name>.srm` in `build/recomp-<variant>/`.

Both variants produce identical code (the patch only changes data), but have separate
build folders, miss logs and save games.

`tools/run.sh --ramlog` additionally writes a RAM recording `evidence/<time>/ramlog.bin`;
the game phase is marked in the game window with keys `0`–`2`, battles with `3` on/off
(`docs/notes/phases.md`).

Environment variables for the game: `AD_CAMPAIGN_START=YY.M.D` (the campaign's first map starts on that date, e.g. `45.4.30`, so later units are on offer; in the game the title menu's row "CAMPAIGN START 1939" chooses the year; `docs/notes/campaign.md`), `AD_AUTO_FF` (automatic fast-forward during enemy turns,
default 128, `0` = off for this launch; in the game System menu → System → "Fast enemy turn" / "Enemy battles", kept in `ad-port.ini`), `AD_FF_LOG=1` (log every change of its speed), `AD_LANG=en|de|fr|es|jp` (tr: start in English, German, French, Spanish or Japanese; in the game System menu → System → "Language", kept in `ad-port.ini`; `docs/notes/translation-rom.md`), `GENESIS_FF_MAX` (fast-forward maximum), see `docs/notes/controls.md`.

Useful runner arguments: `--max-frames N` (quit after N frames), `--turbo` (no frame limiter),
`--fresh-evidence` (start miss logs afresh). Miss logs (`dispatch_misses.toml` etc.)
are in `build/recomp-<variant>/`; generation logs in `build/recomp-<variant>/generated/ad/`.

## release.sh / bps.py – the Mac app for players

Details: `docs/notes/release.md`. The release is a second output of the same sources; the
development build (`build/recomp-tr/`) is not touched.

| Call | Effect |
|---|---|
| `tools/release.sh [--no-hd] [--no-test] [--version X.Y.Z]` | release build of `tr` in `build/release-tr/`, BPS patch, launcher, `build/release/Advanced Daisenryaku.app` + zip; audit (no ROM inside), ad-hoc signature, smoke test (600 frames in a scratch data folder; needs that no game is running) |
| `tools/build.sh --rom tr --release` | only the release build of the game (no debug server, no reverse-debug ring) |
| `tools/bps.py create SOURCE TARGET PATCH` | BPS patch that turns SOURCE into TARGET |
| `tools/bps.py apply SOURCE PATCH TARGET` | apply a BPS patch (CRC32 of source, target and patch checked) |
| `tools/bps.py info PATCH` | sizes, CRC32 values, how many bytes are in the patch itself |

Environment for `release.sh`: `BUNDLE_ID`, `CODESIGN_IDENTITY` (default ad hoc). For the app:
`AD_USER_DIR` (data folder instead of `~/Library/Application Support/Advanced Daisenryaku`),
`AD_ROM` (JP ROM instead of the file dialog).

## win.cmd / win_tool.ps1, release_windows.sh, wincheck.sh – Windows

Setup on the PC, what runs where, unchecked points: `docs/notes/windows.md`.

| Call | Effect |
|---|---|
| `tools\win TOOL [ARGS]` (Windows, PowerShell or cmd) | set up the MSVC x64 environment (vswhere, `Launch-VsDevShell.ps1`), check `cl`/`cmake`/`ninja`/`git`/`python`, run `tools/TOOL.sh ARGS` in Git Bash; `tools\win bash` = an interactive Git Bash with that environment |
| `tools\win release_windows [--no-hd] [--no-test] [--version X.Y.Z]` | release build of `tr` + launcher, BPS patch, folder `build/release/Advanced Daisenryaku/` + zip; audit (no ROM inside), smoke test (600 frames, scratch data folder) |
| `powershell -ExecutionPolicy Bypass -File tools\make_icon.ps1 [-Mac] [-Preview]` (Windows) | draw the icons (大 in the title logo's colours): without `-Mac` the launcher icon `release/windows/icon.ico` (16–256 px), with `-Mac` the Mac app's `release/macos/AppIcon.iconset` (rounded red square, 16–1024 px; `tools/release.sh` turns it into `AppIcon.icns`); `-Preview` writes preview PNGs, not for the repo; run again only to change an icon (`docs/notes/release.md`, "Icon") |
| `tools/wincheck.sh [--rom jp\|en\|tr]` (Mac) | cross-build `ADRecomp.exe` and the launcher with mingw-w64 (`brew install mingw-w64`) into `build/wincheck-<variant>/`: a compile check of the Windows branches without a PC (GCC, not MSVC) |

Environment for the scripts: `PYTHON` (default `python3`, on Windows `python`). For the Windows
launcher: `AD_USER_DIR` (data folder instead of `%APPDATA%\Advanced Daisenryaku`), `AD_ROM`.

## adtext.py / translate_rom.py – text and translation

Text encoding, font and intro captions: `docs/notes/text.md`; translated ROM: `docs/notes/translation-rom.md`.
Character map `translation/charmap.txt`, scripts `translation/script/*.toml`, glossary `translation/glossary.md`.

| Call | Effect |
|---|---|
| `tools/adtext.py intro ROM` | decode the intro captions (JP text) |
| `tools/adtext.py dump ROM ADDR … [--lines N]` | decode N consecutive strings from each address (hex, `$` optional) |
| `tools/adtext.py catalog ROM [--out FILE]` | all known text of the JP ROM as TSV (section, address, format, source, text), counts on stderr; text areas: `docs/notes/text-map.md` |
| `tools/adtext.py briefings ROM` | unpack and print the campaign briefings and result texts (LZSS blocks, `docs/notes/briefings.md`) |
| `tools/srm_convert.py to-emu PORT.srm OUT.srm [--full]` | port save → emulator save (32 KiB odd bytes; `--full` 64 KiB) (`docs/notes/saving.md`) |
| `tools/srm_convert.py to-port EMU.srm OUT.srm` | emulator save (32 KiB, or up to 64 KiB, also trimmed Genesis Plus GX files) → port layout (64 KiB) |
| `tools/srm_convert.py names IN.srm OUT.srm --from EN_ROM --to build/rom/ad-tr.md` | replace the names a save holds from another ROM (army and scenario names are copied into the save, e.g. EN "Germany") by the target ROM's names, recompute the slot checksums; layout kept |
| `tools/nemesis.py unpack ROM ADDR OUT` | unpack Nemesis-packed tiles (game decompressor `$005B1E`, `docs/notes/graphics.md`) to raw 4 bpp tiles |
| `tools/nemesis.py pack IN OUT` | pack raw tiles (plain or XOR mode, whichever is smaller; round trip checked) |
| `tools/translate_rom.py JP_ROM --measure` | width of every English line against its budget, nothing written |
| `tools/translate_rom.py JP_ROM OUT [--game-font]` | write the translated 3 MiB ROM (`tools/build.sh --rom tr` does this itself); text set by the typeface (`tools/hd/typeface.py`, needs macOS), `--game-font` = the game's pixel fonts; also adds the great-victory date to the campaign turn screen (`docs/notes/campaign.md`); further languages from `translation/<code>/*.toml` (German `de`, French `fr`, Spanish `es`) go into the ROM's language block, and the build lists every string that does not fit its box (`docs/notes/translation-rom.md`) |

Name tables (8x8, 8 characters): `translation/script/names-*.toml`, applied by `translate_rom.py`
(`docs/notes/translation-rom.md`).
16x16 strings: `translation/script/text-*.toml` (string redirect, small font `translation/font/small.txt`).
Briefings: `translation/script/brief-*.toml` (paragraphs, word-wrapped; extra glyphs `translation/font/big-extra.txt`).

Needs Python ≥ 3.11 (tomllib), no packages.

## fold.sh – take over interpreter evidence as functions

What the recompiler didn't find is executed by the tier-3 interpreter and logged
(`floor_coverage.toml`, with `run.sh` additionally `exec_pcs.txt` = executed instructions).
`tools/fold.sh [--rom jp|en]` collects all evidence (`build/recomp-*/`, `…/evidence/*/`,
`build/archiv/**`), checks it with `tools/fold_floor_coverage.py` and writes
`recomp/game/ad_floor.discovery.toml` (`late_extra`, not recursive).

A target is taken over if it is not an interior label (not inside an existing function),
its straight run up to the first jump decodes cleanly and – if an instruction list covers it –
every one of these instructions was executed (otherwise marked "static").
Gate: `tools/compare_native_coverage.py` compares probe generations before/after;
if a native instruction is lost, the discovery and deny files are restored.

Deny list `recomp/game/ad_floor.deny.toml` (recompiler blacklist): if the runner reports an
unsafe interpreter jump (`[FLOOR][UNSAFE]`, `floor_unsafe.toml`) or an interior label
in a function taken over by a fold, `fold.sh` automatically denies the whole subtree from its
floor root – it runs completely in the interpreter again (state before the fold). The gate
allows exactly these losses. Entries may also be added by hand.
Limit: the gate does not detect runtime stack errors – only play runs show those.

Cycle: `tools/build.sh` → `tools/run.sh` (play, quit normally) → `tools/fold.sh` → repeat.
Needs Python with `capstone` (otherwise automatically `uv run --with capstone`; uv is in the Brewfile).

### dispatch_scan.py – interpreter entries, found statically

`uv run --with capstone tools/dispatch_scan.py [--toml]` lists code pointers in the ROM that have
no generated function (menu-table handlers, `move.l #handler,…`): the places where the
interpreter can still be entered, with a class per target (`entry`, `fall`, `STACK`). Checked
targets go into `late_extra` in `recomp/game/game.toml` by hand, with the gate of
`compare_native_coverage.py` (`docs/notes/recompiler-runs.md`, "Seeding rules").

## textscan.py – find Japanese text on screen

Samples the VDP state of the running game through the runner's TCP debug server and reports every
Japanese glyph of the JP fonts that is visible (16x16 kana/kanji, 8x8 katakana) – leftovers in the
`tr` build. Method and validation: `docs/notes/textscan.md`.

| Call | Effect |
|---|---|
| `tools/textscan.py run [--rom tr] [--script FILE] [--frames N]` | start the game headless through `run.sh` (turbo; `--no-turbo`), driven by an input script, scan until it exits |
| `tools/textscan.py run --script tools/textscan/standard.txt` | route: STANDARD menu, scenario list, status pages, turn screen, map, START menu |
| `tools/textscan.py debug on [--rom tr]`, then `tools/run.sh --rom tr` | enable the debug server (`debug.ini`, port 4390) for a normal play session |
| `tools/textscan.py watch` | scan the game started like that while playing; ends with the game or Ctrl+C |
| `tools/textscan.py debug off [--rom tr]` | remove `debug.ini` again |
| `tools/textscan.py check SNAPSHOT.json …` | scan saved snapshots again (after changing the tool) |

Report: `build/textscan/<time>/report.md` – each distinct line once (first frame, position, number
of samples) with a screenshot and a VDP snapshot. Exit code 1 if Japanese text was found.
`run` creates `debug.ini` only for that run and backs up/restores the build folder's save games
(`*.srm`), since a script can change settings. Input scripts: runner format
(`docs/notes/work-environment.md`, `SCREENSHOT`, `PRESS`, `WAIT` …).

## hdpack.py / hdart.py – HD graphics (4x)

`docs/notes/hd-graphics.md`. The pack is built for the `tr` variant.

| Call | Effect |
|---|---|
| `tools/hdpack.py build` | text from the translation build at 4x (typeface Nunito Sans, `tools/hd/fonts/`, via `tools/hd/typeface.py` / CoreText `tools/hd/glyphs.swift`, the same fonts that set the ROM text) + redrawn art (`build/hd/art.bin`) → `build/hd/pack.bin` |
| `tools/hdpack.py preview TEXT… [--font small]` | 1x and 4x of a text → `build/hd/preview-*.png` |
| `tools/hdart.py watch` | collect the tiles on screen while playing (debug server: `tools/textscan.py debug on`) → `assets/hd/catalog.json` |
| `tools/hdart.py add SNAPSHOT.json…` | the same from saved `vdp_state` dumps |
| `tools/hdart.py export` | new tiles → screen-shaped sheets `assets/hd/sheets/NNN-A\|B\|S.png` to redraw at 4x |
| `tools/hdart.py import` | redrawn cells → `build/hd/art.bin` (then `hdpack.py build`) |
| `tools/hdart.py status` | collected / exported / redrawn |

## ramphase.py – find game phases in RAM

Analyses RAM recordings from `tools/run.sh --ramlog` (phases 0 other, 1 own turn,
2 enemy turn, 3 battle; `docs/notes/phases.md`). Runs via `uv` (fetches numpy itself).

| Call | Effect |
|---|---|
| `tools/ramphase.py LOG [LOG …]` | RAM bytes and bits whose values during the enemy turn never occur in the own turn or a battle |
| `tools/ramphase.py LOG --target 3 --against 1 2` | the same for battle against own turn + enemy turn |
| `tools/ramphase.py LOG --show FF0110 FFCDA0` | history of these addresses with the phase |
| `tools/ramphase.py LOG --phases` | marked phases with their duration |

`--margin N` (default 60): ignore records for N V-ints after each phase change (hand marking lags).
`--count N`: length of the candidate lists. Perfect separators sorted by the number of distinct
values (flags first). Then "fuzzy separators": balanced hit rate per byte/bit (50 % = does not
separate, 100 % = perfect) with the value distribution – needed with several recordings, because
the hand marking lags at the phase boundaries.

## recompiler_update.sh

Keeps segagenesisrecomp on the commit in `recomp/RECOMPILER_COMMIT` and raises it deliberately.
Reads `RECOMPILER_DIR` and the ROM paths from `config.env`. Needs cmake, ninja (Brewfile).

| Call | Effect |
|---|---|
| `tools/recompiler_update.sh check` | compare pin and checkout, build present? Exit 0 = ok |
| `tools/recompiler_update.sh sync` | set the checkout to the pin, submodules, build the recompiler (new machine) |
| `tools/recompiler_update.sh test` | framework tests (`ctest`) at the current state; leaves out `FLAKY_TESTS` (ctest regex, default `host_stream_exit_1_1`, on Windows also `disasm_inline_tables` and `segacd_register_span_catalog`; `FLAKY_TESTS='^$'` runs all); on Windows puts the bundled `SDL2.dll` on PATH and passes `%TEMP%` in its long form |
| `tools/recompiler_update.sh patch` | apply our framework patches from `recomp/patches/` (idempotent) |
| `tools/recompiler_update.sh update [REF]` | raise to `REF` (default `origin/HEAD` = default branch `master`) |

`update` in detail:
1. Abort on local changes in the recompiler checkout.
2. `fetch`, shows new commits.
3. Checkout + submodules, build the recompiler, framework tests (`ctest`),
   generate C code (as a probe with the JP ROM).
4. All green → write and commit the pin (don't push).
   Any error → back to the old pin, rebuild, exit 1.

Afterwards by hand: boot the game to the title screen.

Our own framework fixes are kept as `recomp/patches/NNNN-*.patch` and applied as a stack
in order (patches may build on each other). The total diff is stored as a stamp
in `<recompiler>/.git/ad-patches.diff`; from it the script recognises the active stack and
reverts it exactly. `build.sh` applies, `sync`/`update` revert before the checkout and
re-apply afterwards. `check` accepts changes in the checkout only if they match the stamp.
A patch that no longer applies after an update makes `update` fail (→ rollback).

Example:
```sh
tools/recompiler_update.sh update            # latest master
tools/recompiler_update.sh update v0.1.3     # a specific tag
```

Note: after `sync`/`update` the recompiler checkout is on a fixed commit (detached HEAD).
That is intended.

## mapzoom.py – zoomed-out hex map (prototype)

Redraws any part of the hex map the way the game would, from a RAM dump + the ROM + the map
screen's VRAM/CRAM: terrain, fog / movement range, units with their marks, the cursor
(`docs/notes/map.md`, "Zoomed-out map prototype"). Inputs come from the debug server:
`read_memory` of `$FF0000-$FFFFFF` (64 KiB file), `vdp_state` with `include="vram,cram,vsram"`,
`screenshot`.

| Call | Effect |
|---|---|
| `tools/mapzoom.py render RAM VDP.json OUT.png --area zoom` | twice the game's view in each direction (half-size hexes), centred on it; `--area view` = the game's own viewport, `--area map` = the whole map; `--scale N`, `--no-cursor` |
| `tools/mapzoom.py check RAM VDP.json SCREEN.png` | render the game's viewport and compare with the screenshot: every (palette index, shadow) of the render must map to one screen colour; prints where it does not |

Colours in the PNGs are approximate (CRAM × 36, shadow = half) – for looking only. Default ROM
`build/rom/ad-tr.md` (`--rom`).

## drive.py – headless test runs through the debug server

Plays the game from boot by a list of steps (buttons, waits, screenshots, RAM/VDP dumps, scenario
list row, map cursor to a hex) through the debug server (port 4390; `tools/textscan.py debug on`).
Start it next to the game; **check first that no other game instance runs** (`pgrep -fl ADRecomp`).
Routes and pitfalls: `docs/notes/work-environment.md` ("Test routes").

| Call | Effect |
|---|---|
| `tools/drive.py --out DIR STEP… & tools/run.sh --rom tr` | run the steps (`W:n`, `A[:n]`, `H:LEFT,n`, `S:name`, `V:name`, `R:name`, `G:row`, `X:x,y`, `Q`; see `--help`) |
| `tools/drive.py --file STEPS.txt --out DIR` | steps from a file |

More steps: `Z:name` dumps the 8 KiB Z80 RAM (sound driver), `ZS` prints the Z80 registers, `WAV:name` … `WAV:stop` records the sound output (`docs/notes/sound.md`).
