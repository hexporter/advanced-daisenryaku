# Windows build

The port also builds for Windows x64 from the same sources. Toolchain: **MSVC** (Visual Studio 2022
Build Tools), the toolchain the framework supports on Windows (its README: "Windows (MSVC)";
upstream's Sonic CD release is Windows x64). The bash tools run unchanged in **Git Bash**;
`tools\win.cmd` / `tools\win_tool.ps1` set up the MSVC environment and start them.

**Status: the tr build compiles with MSVC and plays on Windows 11** (`tools\win build|run --rom
tr`, Direct3D 11 renderer, an 8BitDo pad, sound): a session of 104 180 frames (intro, soft reset,
a save from the Mac loaded, a new map, battles in both directions, saving) interpreted nothing and
left all four miss files empty. `tools\win release_windows` builds the folder and the zip and
passes its smoke test. Still unchecked on Windows: see "To check on the PC" below. On the Mac
`tools/wincheck.sh` cross-builds both executables with mingw-w64 as a compile check.

## What runs where

| Step | Mac | Windows |
|---|---|---|
| framework checkout, patches, recompiler, C generation, compile | yes | yes (generation is part of the CMake build, `GenesisRecomp.exe`) |
| jp / en builds | yes | yes |
| translated ROM `build/rom/ad-tr.md` (`translate_rom.py`) | yes | **no** – the typeface is rasterised with CoreText (`tools/hd/glyphs.swift`) |
| HD pack `build/hd/pack.bin` (`hdpack.py`) | yes | **no** – same reason |
| game, framework tests, release folder | yes | yes |

So for tr: make the ROM and the HD pack on the Mac (`tools/build.sh --rom tr`, `tools/hdpack.py
build`), copy both to the PC. `build.sh` on a machine without `swift` uses an existing
`build/rom/ad-tr.md` as it is (it says so); without one it tries `translate_rom.py` and fails.
Copy them again after every change to the translation or the HD text.

## Install on the PC (once)

In PowerShell (winget is part of Windows 10/11):

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
winget install Git.Git
winget install Python.Python.3.12
winget install Gyan.FFmpeg        # optional: video recording with L3
```

- Build Tools: workload "Desktop development with C++" with its recommended parts – MSVC x64,
  Windows SDK, **C++ CMake tools for Windows** (brings `cmake` and `ninja`). The full Visual Studio
  Community works as well.
- Python ≥ 3.11 (`tomllib`). The scripts call it as `python` (`PYTHON=…` overrides).
- SDL2 needs no install: the framework ships the SDL2 2.28.5 VC package
  (`runner/external/SDL2/SDL2-2.28.5`); the build copies `SDL2.dll` next to `ADRecomp.exe`.

**Line endings – before cloning:** Git for Windows checks text out as CRLF by default; the framework
patches then no longer apply and bash scripts break. Once:

```powershell
git config --global core.autocrlf false
```

(This repo's `.gitattributes` keeps `*.sh`, `*.patch`, `*.py`, `*.toml` LF anyway; the framework
checkout has no such file.)

## Set up the folders

A short path without spaces and outside OneDrive, e.g. `C:\RecompProject`:

```powershell
cd C:\RecompProject
git clone <your remote of this repo> advanced-daisenryaku
git clone --recursive https://github.com/mstan/segagenesisrecomp.git
cd advanced-daisenryaku
copy config.example.env config.env
```

`config.env` with Windows paths in the form `C:/…` (forward slashes; not `$HOME`, which is
`/c/Users/…` in Git Bash):

```sh
ROM_JP_PATH="C:/RecompProject/_roms/Advanced Daisenryaku - Deutsch Dengeki Sakusen (Japan) (Rev A).md"
ROM_EN_PATH="C:/RecompProject/_roms/Advanced Daisenryaku - english.md"
ROM_VARIANT=tr
RECOMPILER_DIR="C:/RecompProject/segagenesisrecomp"
```

From the Mac (USB stick, network share): the JP ROM to `_roms\`, `build/rom/ad-tr.md` to
`build\rom\`, `build/hd/pack.bin` to `build\hd\`. To continue a save game:
`build/recomp-tr/ad-tr.srm` to `build\recomp-tr\` (after the first build).

## Build and play

From `C:\RecompProject\advanced-daisenryaku`, in PowerShell or cmd:

```powershell
tools\win recompiler_update sync     # framework to the pin, patches, build GenesisRecomp.exe
tools\win build --rom tr             # generate + compile → build\recomp-tr\ADRecomp.exe
tools\win run --rom tr               # play (HD, 16:9 as on the Mac)
tools\win recompiler_update test     # framework tests (optional)
tools\win bash                       # a Git Bash with the MSVC environment, for anything else
```

`tools\win <name> …` runs `tools/<name>.sh …` (`win.cmd` → `win_tool.ps1` with `-ExecutionPolicy
Bypass`, so no PowerShell policy has to change). The first build compiles the whole generated
program and takes a while.

Save game, `settings.ini`, `ad-port.ini`, miss logs and `run.log` are in `build\recomp-tr\`
as on the Mac. Videos (L3) go to `build\video\` (release: `%APPDATA%\Advanced
Daisenryaku\video\`); ffmpeg must be on PATH; the encoder is `libx264`,
`AD_REC_CODEC=h264_nvenc` uses an NVIDIA GPU. Recording runs at full speed (`controls.md`).

## Windows version for players

```powershell
tools\win release_windows            # [--no-hd] [--no-test] [--version X.Y.Z]
```

Builds `build\release\Advanced Daisenryaku\` and `AdvancedDaisenryaku-<version>-windows-x64.zip`:

```
Advanced Daisenryaku\
  Advanced Daisenryaku.exe   launcher (release/windows/launcher.c, CMake target ADLauncher)
  ADRecomp.exe, SDL2.dll     the game (release build, build\release-tr\)
  translation.bps            patch JP ROM → translated ROM (as in the Mac app)
  pack.bin                   HD pack (left out with --no-hd)
  settings.ini, README.txt, LICENSE, THIRD-PARTY-LICENSES.md, SDL-LICENSE.txt
```

The launcher does what the Mac launcher does (`release.md`): data folder
`%APPDATA%\Advanced Daisenryaku` (`AD_USER_DIR` overrides), asks once for the JP ROM (file
dialog; `AD_ROM` for tests), checks size and CRC32, applies the patch, remembers the source in
`rom-source.txt`, seeds `settings.ini`, sets `GENESIS_USER_DIR`, `GENESIS_HD_PACK`,
`GENESIS_NO_LAUNCHER` and starts `ADRecomp.exe`; it waits for the game and returns its exit
code. It is a GUI program: started from Explorer there is no console window, and the output of
launcher and game goes to `run.log` in the data folder. With the HD pack it sets
`GENESIS_HD_MARGIN=39`, so the release is 16:9 like `tools\win run` (a margin set in the
environment wins; without `pack.bin` the picture stays 4:3), as the Mac app. CRC32, BPS and the ROM steps are shared with the Mac launcher
(`release/common/rompatch.h`).

Both executables carry `release/windows/utf8.manifest` (UTF-8 as the process code page,
Windows 10 1903+), so paths with non-ASCII letters (a user name in `%APPDATA%`) work with
`fopen`. The script refuses to package a ROM, save, log, `.pdb`, `debug.ini` or `GenesisRecomp`,
and runs a smoke test like `release.sh` (launcher with `AD_ROM` in a scratch folder, 600 frames,
ROM identical, no misses). Not signed: SmartScreen warns on other PCs ("More info" → "Run
anyway") until the files are signed with a code-signing certificate.

## What the port changes for Windows

- Framework patch `0013-msvc-hd-bit-counts`: MSVC has no `__builtin_popcount/ctz/clz`
  (patch 0007 uses them); portable versions under `_MSC_VER`.
- Framework patch `0014-windows-dpi-awareness`: before `SDL_Init` the runner sets
  `SDL_HINT_WINDOWS_DPI_AWARENESS=permonitorv2` and `SDL_HINT_WINDOWS_DPI_SCALING=1`. Without
  them the process is DPI-unaware: under display scaling (e.g. 200 %) SDL renders at 100 %
  (renderer output 796x448 for a 796x448 window) and Windows stretches the window with a soft
  filter – a blurred picture. With them the window keeps its size in points and the renderer
  draws physical pixels (1592x896 at 200 %), as with Retina on the Mac. The environment
  variables `SDL_WINDOWS_DPI_AWARENESS` / `SDL_WINDOWS_DPI_SCALING` still override.
  `GENESIS_DISPLAY_TRACE=1` logs the output size (`[display] … output=`).
- `recomp/CMakeLists.txt`: SDL2 from the framework's VC package, `SDL2.dll` copied after the
  build, `/utf-8 /bigobj`, the manifest, target `ADLauncher`, static C runtime
  (`CMAKE_MSVC_RUNTIME_LIBRARY`: players need no Visual C++ Redistributable).
- `ad_record.c`: `_popen(…, "wb")` (binary pipe), `_mkdir`, no `SIGPIPE`, ffmpeg from PATH,
  `libx264`; `AD_REC_CODEC` chooses the encoder on both systems.
- Scripts: `rom_select.sh` sets `AD_WINDOWS`, `EXE=.exe`, `PYTHON` and turns `ROOT` into `C:/…`
  (`pwd -W`); `build.sh` copies the ROM instead of a symlink, uses `cl`, skips the translation
  without `swift`; `recompiler_update.sh` finds `GenesisRecomp.exe` and the SDL2 package for the
  tests.
- Unchanged and portable already: the data-folder code (`GENESIS_USER_DIR` + `/`, which Windows
  accepts), the game fiber (minicoro's Win64 switch, which also moves the TIB stack bounds), the
  debug server (TCP).

## Checking Windows code on the Mac

`tools/wincheck.sh [--rom tr]` (needs `brew install mingw-w64`) cross-builds both executables into
`build/wincheck-<variant>/`, with the Mac's `GenesisRecomp` generating the C code. It catches POSIX
calls and missing `#ifdef _WIN32` branches; MSVC-only problems (GCC extensions such as the
builtins of patch 0007) it does not see.

## To check on the PC

Works under MSVC: the build, the framework tests (`tools\win recompiler_update test`: 130 pass,
two upstream tests left out, `recompiler.md`), boot, sound, controller, HD with the 16:9 frame, the zoomed map,
automatic fast-forward in enemy turns, saving, the sharp picture under display scaling (patch
0014), and the paths that leave a call chain by `longjmp` off the game fiber (`ad_spec.c`):
Record → Load, Record → Quit (to the title menu), Record → Restart and the soft reset out of the
V-int (START during the intro). MSVC's `longjmp` unwinds the native
frames (SEH) instead of just restoring registers, and that works on the fiber stack (minicoro
updates the TIB stack limits on every switch). F10 / F9 in play, fast-forward on the right
trigger. Restart needs a map begun with a build that has it (or a save made since); with an
older save the row stays "Give up", which does nothing in the campaign (`campaign.md`).

`tools\win release_windows`: folder and zip as listed above, `ADRecomp.exe` identical to
`build\release-tr\`; smoke test passed (launcher with `AD_ROM`, ROM patched identically, 600
frames, no misses). Both executables import only system DLLs and `SDL2.dll` (static C runtime:
no Visual C++ Redistributable needed). The zip unpacked with the download mark
(`Zone.Identifier`, ZoneId 3) and started from Explorer on the build PC: SmartScreen warning,
ROM question, a wrong file (message, Cancel quits), the JP ROM, play / save / load, no question
on the next start; `ad-tr.md` deleted and the ROM moved → asked again. The launcher shows the
icon 大 (`release.md`, "Icon").

`drive.py` and `textscan.py debug on|off` work in Git Bash on Windows (screenshots through the
debug server).

Open:

1. The release on a second PC without the build tools.
2. Not adapted or tried: `fold.sh`, `ramphase.py` on Windows (plain bash/Python, may just
   work), `--ramlog`.

The runner logs `[VIDEO] window … (4:3)` in the HD 16:9 frame too: the label reflects only the
framework's own widescreen mode (`runner/main.c`), not the port's HD margins.
