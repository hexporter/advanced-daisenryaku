# Work environment: headless runs and test routes

For developers and AI agents driving the game without a person at the window.

## Setup

- Everything runs on an Apple silicon Mac: `tools/build.sh`, framework tests
  (`tools/recompiler_update.sh test`), headless runs. A visual change still needs a look at the
  real window by a person.
- Linux can run probe generations and `fold.sh`
  (`CONFIG_ENV=<Linux paths> GENESIS_RECOMP=<Linux GenesisRecomp> tools/fold.sh`) but builds no
  Mac binaries.
- Windows code can be checked here without a PC: `tools/wincheck.sh` (mingw-w64 from Homebrew is
  installed) cross-builds `ADRecomp.exe` and the launcher; running it needs a Windows PC
  (`windows.md`).
- Disassembly: capstone (68000, `CS_MODE_M68K_000`) via `uv run --with capstone`, z80dis for
  the Z80 driver.

## Headless runs

- `tools/drive.py --out <absolute DIR> <steps> & tools/run.sh --rom tr` drives the game through
  the debug server (`debug.ini` in the build folder, port 4390; `tools/textscan.py debug on`).
  `--out` must be absolute: the game writes the screenshots and its folder is the build folder.
  Screenshots also write `<name>.hd.png`.
- **One game instance at a time:** before every run `pgrep -fl ADRecomp`, as a gate
  (`if pgrep -fl ADRecomp; then exit 1; fi`), not as a line whose output scrolls past. `run.sh` does not
  stop a running game; a second instance cannot bind the port and the driver would talk to the
  other game.
- **Protect the save file:** `cp -p build/recomp-tr/ad-tr.srm <copy>` before a run, `cmp`
  afterwards, copy back on a difference. Runs that only play from boot do not write SRAM, but a
  route through the Record menu can (a missed cursor press turns Load into Save), and CONTINUE
  on the title menu loads the real save.
- Do not use `--turbo` for routes with timed presses; it is fine for boot-to-map checks.
- `AD_MAP_ZOOM=0` gives the game's own map, `AD_AUTO_FF=0` keeps enemy turns at normal speed.
- `AD_LANG=en|de|fr|es|jp` starts in that language without touching the stored choice. A route that
  presses A on the "Language" row writes `build/recomp-tr/ad-port.ini`: check it after the run,
  the next normal start uses that language.
- Savestates do not restore this game (garbled screen): always play from boot.
- Ctrl+C ends `run.sh` without evidence; quit through the driver (`Q`) or the window.
- In zsh a route kept in a variable needs `${=ROUTE}` to split into steps.

## Driver quirks

- A `DOWN` press sometimes moves two rows (lists, title menu); `UP` from the first row wraps
  to the last. Take a screenshot before every `A` that confirms something. A 2-frame hold is
  not seen at all. On the title menu the highlighted row is green: a script can read it from a
  screenshot (rows at y 80 + 16·n, x 128–200) and steer by it.
- `A` on the title menu's button-layout row ("A-MAIN C-SUB") swaps A and C and stores it in
  SRAM `$20FFF9`/`$20FFFB` (`menu.md`): after that `A` confirms nothing and every route fails.
  Restore by writing `$FF` to bytes `$FFF9` and `$FFFB` of `build/recomp-<v>/ad-<v>.srm`
  while the game is closed.
- The `G:row` step (scenario list) does not find the highlighted row; use `DOWN:60` presses
  and a screenshot (9 presses end on row 13, Greece: a large map, X 12–49).
- Screenshot steps add two frames; the same presses without them can end elsewhere (the
  system-menu route below ended on Weather without its two screenshots).

## Test routes (tr, `tools/drive.py`)

Frame numbers are V-ints; button waits absorb load times.

| Goal | Steps |
|---|---|
| title menu | `W:600 START:120` (START skips the intro); cursor on CONTINUE |
| settings menu (STANDARD) | … `DOWN:20 DOWN:20 A:200` (cursor on "Load") |
| scenario list | … `A:300`; `A:300 UP:40 A:900` loads and starts, `A:200` skips the turn screen. Maginot = row 9 (50x50) |
| scenario 0 ("Case Wht") map | `W:600 START:120 DOWN:20 DOWN:20 A:200 A:200 A:200 UP:30 A:900 W:100 A:200 W:60` |
| unit command menu | on the map `A:120` (cursor starts on the Grenadiers at (24,31)) |
| move | `X:27,34 A:120 A:150 X:29,34 A:200` (PzKw I A next to the enemy cavalry at (30,34)) |
| attack after the move | `A:150 A:150 A:150` (Attack, weapon, target), then `A` starts the battle |
| end the turn | on the map `START:60 DOWN:20 A:200`, then the enemy turns (~1500 frames) |
| campaign, first turn screen | `W:600 START:120 DOWN:20 A:400`, then 5 × `H:A,120 START:60` (briefing pages) |
| start-year row | title menu `UP:30` (wraps to the row; it can land one row higher, on the button-layout row, where `A` writes SRAM `$20FFF9`/`$20FFFB`), `A:40` per year |
| map menu (Automation, Map, Units, Status, Income, Develop.) | on the map `C:90 C:120` |
| system menu (Record, Sound, Control, Fog, Weather, System) | on the map `C:90 C:120 C:120` |
| System settings screen | … `S:x UP:40 S:x A:150` (UP wraps to System) |
| Language row | settings screen `UP:40` (wraps to the last row), `A:60` switches; keep the screenshot steps of the system-menu route |
| campaign briefing, page 1 typed | `W:600 START:120 DOWN:20 A:400 H:A,120 START:60 W:150 H:A,120` |
| Record menu (Save, Load, Give up, Quit) | system menu `A:120`; one `DOWN:60` per row; the yes/no dialog opens on Cancel, `DOWN:60 A` = Exec. |

Units of scenario 0 at the start: Grenadiers (24,31), PzKw I A (27,34), enemy Cavalry (30,34);
view origin (23,29).

## Screenshots, videos, recordings

- Input script (`--input-script`): `SCREENSHOT <path>` + `WAIT 1` per frame, `EXIT 0`; audio with
  `--wav`. A script holds at most 4096 directives. On `EXIT` the WAV header is not finalised:
  read the data as raw PCM (`tail -c +45`, `-f s16le -ar 223721 -ac 2`). `DUMP_VRAM` /
  `DUMP_RAM` dump at an exact frame.
- Recordings made in play (L3, `controls.md`) are the quickest way to a visual bug: find the
  frames in the csv/bin first, then cut those frames from the mp4 at full size.

## Shell pitfalls

- macOS bash 3.2: no `globstar`; empty arrays under `set -u` need `${a[@]+"${a[@]}"}`.
