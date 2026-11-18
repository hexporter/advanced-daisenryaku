# Recompiler (segagenesisrecomp)

Framework: **segagenesisrecomp** (mstan), sibling folder `~/RecompProject/segagenesisrecomp`,
pinned to `master` @ `76490c6` (`recomp/RECOMPILER_COMMIT`).

## Why this one

| Criterion | segagenesisrecomp (mstan) | genrecomp (sp00nznet) |
|---|---|---|
| macOS | official (Apple Silicon + Intel) | untested |
| Missing functions at runtime | interpreter fallback, game keeps running, miss is logged | no fallback, seeds by hand |
| Hardware | own clean-room VDP/bus/YM2612/SN76489/Z80 | Genesis Plus GX |
| H-int | supported (RAM trampoline) | missing |
| Config / generator | `game.toml`, C11, CMake/Ninja | `recomp.json`, Python + capstone |
| License | PolyForm Noncommercial 1.0.0 | MIT + GPGX (non-commercial) |

macOS is the main platform (Windows second, `windows.md`); there is no disassembly, so the interpreter fallback is what
makes heuristic discovery workable (`recompiler-runs.md`); the framework's RKA port
(`rka/game.toml`: 1 MiB, flat, no disassembly, H-int in RAM) is structurally like this ROM.
Drawback: a large, fast-moving framework – hence the pin.

## Working with the framework

- Clone only recursively (submodules use relative URLs; ZIP downloads are incomplete).
- New games live in their own repo; this project's config is in `recomp/`.
- **Pin:** raise it only with `tools/recompiler_update.sh update` (builds, tests, generates,
  commits the pin on success, rolls back otherwise). Upstream rewrote `master` once
  (07.11.2026) and moved its tags, so old hashes can vanish from a fresh clone; the script
  fetches without `--tags`.
- **Our changes are patches** in `recomp/patches/NNNN-*.patch`, applied as a stack by
  `tools/recompiler_update.sh` (`patch`; automatically in `build.sh`, `sync`, `update`). The
  checkout is never committed. New patch: copy the files before editing, write the diff against
  the applied stack (`diff -u --label a/… --label b/…`), restore the copies, let `build.sh`
  re-apply the stack. A patch that adds a function `genesis_machine.c` calls needs a stub in
  `tests/runtime/genesis_machine_sram_state_test.c`.
- Patches that enlarge `GenesisBus` make old `native_save_*.bin` unusable (`.srm` is not affected).
- Framework tests: `tools/recompiler_update.sh test` (132 tests). `host_stream_exit_1_1`
  segfaults in about two of three runs on this Mac (upstream race at host writer exit, none of
  our files involved) and is left out (`FLAKY_TESTS`). On Windows all others pass except two
  that assume upstream's setup, also left out there: `disasm_inline_tables`
  (`gen_disasm_jumptables.py` takes `Path(__file__).parents[5]`, so it needs the checkout five
  folders deep) and `segacd_register_span_catalog` (expects `Release/flow.exe` of a Visual
  Studio generator; we use Ninja).
- The tests compile with `/W4 /WX` under MSVC: a warning in patched framework code fails the
  test build (MSVC C4132, a `const` array without initializer, is no warning for GCC/Clang).

## Patches

| Patch | What it does | Notes |
|---|---|---|
| `0002-sram-64k` | SRAM buffer 16 → 64 KiB | `saving.md` |
| `0003-ym-timer-a-and-load-edge` | YM2612 timer A; timers restart only on load bit 0→1 | `sound.md` |
| `0004-analog-fast-forward-right-trigger` | fast-forward with the right trigger, 1×–128× (`GENESIS_FF_MAX`) | `controls.md` |
| `0005-game-requested-fast-forward` | the game requests fast-forward (`g_game_ff_request`; maximum with the trigger) | `controls.md`, `phases.md` |
| `0006-interp-guard-per-frame` | the interpreter's instruction guard counts per frame, so code waiting for V-ints in a capsule is no runaway | `saving.md` |
| `0007-vdp-hd-tile-pack-presentation` | HD presentation: every line rendered again at 4x with tiles from an HD pack, F10 toggles, `.hd.png` screenshots | `hd-graphics.md` |
| `0008-vdp-hd-presentation-hooks` | game hooks into the HD frame: rewrite the sampled plane rows of a line, leave sprites out or move them sideways | `map.md` |
| `0009-vdp-hd-cell-alignment` | HD text cells: a tile first tries the 16x16 cell alignment of an already resolved neighbour | `hd-graphics.md` |
| `0010-vdp-hd-side-margins` | `GENESIS_HD_MARGIN=<px>` (max 48; 39 = 16:9) widens the HD frame and the window's canvas, picture in the middle; a game hook may fill the margins per line (composed like planes, no sprites), otherwise black. `GENESIS_HD_STRIDE` 1664 | `map.md` |
| `0011-hd-margin-argb-hook` | `genesis_hd_set_margin_argb_hook`: on every HD row whose margins the VDP margin hook left black, a game hook may write ARGB pixels into both margins (art that is not made of the game's palette) | `frame.md` |
| `0012-ff-speed-drop` | when the fast-forward speed falls (e.g. 128× → 2×) the presentation counter `ff_acc` is cut to the new speed – otherwise every frame is presented (normal speed, silent) until it has run down, up to ~2 s | `controls.md` |
| `0013-msvc-hd-bit-counts` | `hd_popcount/ctz/clz` in `genesis_vdp.c` instead of the GCC builtins of patch 0007: MSVC has none | `windows.md` |
| `0014-windows-dpi-awareness` | SDL DPI hints before `SDL_Init` on Windows: renders at the display's physical resolution under display scaling instead of being stretched (blurred) by Windows | `windows.md` |
| `0015-vdp-ignore-data-write-in-read-mode` | a data-port write while the VDP is set to a read code (VRAM/CRAM/VSRAM read) stores nothing, the address still advances (as Genesis Plus GX); before, it went to VRAM | `graphics.md` (rain dots) |

Upstream already has what earlier patches did: shadow/highlight priority for transparent pixels
(`graphics.md`) and always-mapped cartridge SRAM above the ROM end.

Upstream has an "HD" of its own (`genesis_raster_jobs`, `genesis_hd_gpu`: native-density jobs
for a GPU raster, no tile replacement); no name clash with our `gvdp_hd_*` functions. Our HD row
hooks in before the final-pixel sink (`native_row_prepare`, then `hd_frame_row`).

## Windows

The framework builds and runs on Windows with MSVC (its README; game fiber via minicoro's Win64
switch, `/CETCOMPAT:NO` set by `GenesisRecompRunner.cmake`, SDL2 2.28.5 VC package bundled in
`runner/external/SDL2`). C generation is part of the CMake build, so it runs on Windows too;
`GENESIS_RECOMPILER_EXE` takes a host recompiler for cross builds (`tools/wincheck.sh`). Setup,
what the port changes and what is unchecked: `windows.md`.

## macOS pitfalls (handled by the scripts)

- **C++ standard:** Apple clang defaults to C++98; ymfm needs ≥ C++11. `-DCMAKE_CXX_STANDARD=17`
  (`recompiler_update.sh`; the game build sets it in `recomp/CMakeLists.txt`).
- **`_POSIX_C_SOURCE`** in `runner/cd/debug.c` hides `INADDR_LOOPBACK` on macOS:
  `-D_DARWIN_C_SOURCE` in `CMAKE_C_FLAGS` (`recompiler_update.sh`, `build.sh`).
- **Temp path symlink** (`/var` → `/private/var`) breaks two Sega CD Python tests: `TMPDIR` is
  resolved with `pwd -P` before `ctest`.
