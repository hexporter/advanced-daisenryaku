# Release: the Mac app

The Windows counterpart (a folder with `Advanced Daisenryaku.exe`, `tools/release_windows.sh`)
follows the same rules and is described in `windows.md`.

One command, `tools/release.sh`, builds `build/release/Advanced Daisenryaku.app` and a zip of it.

## Rule: the release is a second output, not a second code base

- Same sources, same `recomp/CMakeLists.txt`, same patches. A release differs from the
  development build only by two CMake options and by its folders.
- Nothing of the development build is touched: `build/recomp-tr/` (binary, save game, evidence,
  `debug.ini`) stays as it is; the fold cycle `build.sh → run.sh → fold.sh` works as before.
- New features and fixes are made and tested in the development build as always; a release is
  then just `tools/release.sh` again. Do not fix anything in `build/release*` by hand.

| | Development | Release |
|---|---|---|
| Build | `tools/build.sh --rom tr` | `tools/build.sh --rom tr --release` (called by `release.sh`) |
| Folder | `build/recomp-tr/` | `build/release-tr/` (game), `build/release/` (app, zip) |
| `GEN_ENABLE_TRACE`, `SONIC_REVERSE_DEBUG` | ON | OFF (no debug server, no WRAM store ring) |
| ROM | `build/rom/ad-tr.md` | made on the player's Mac from their JP ROM |
| Save game, settings | next to the binary | `~/Library/Application Support/Advanced Daisenryaku/` |
| Start | `tools/run.sh --rom tr` | double-click; launcher `release/macos/launcher.c` |

Without the debug server `tools/drive.py` and `tools/textscan.py` cannot attach to the release
build; they are development tools. The interpreter fallback, the miss logs (`dispatch_misses.toml`
etc., written to the data folder), F9/F10, fast-forward, the L3 recording and the added menu
rows are in both. 16:9 as with `tools/run.sh`: both launchers (Mac and Windows) set
`GENESIS_HD_MARGIN=39` when the HD pack is used; a margin set in the environment wins, and
without `pack.bin` the picture stays 4:3.

## The app

```
Advanced Daisenryaku.app/Contents/
  MacOS/Advanced Daisenryaku   launcher (release/macos/launcher.c)
  MacOS/ADRecomp               the game (release build)
  Frameworks/libSDL2-2.0.0.dylib, libSDL3.dylib
  Resources/translation.bps    patch JP ROM → translated ROM
  Resources/pack.bin           HD text/tile pack (left out with --no-hd)
  Resources/settings.ini       controller layout, copied to the data folder once
  Resources/LICENSE, PERMISSIONS.txt, THIRD-PARTY-LICENSES.md, SDL-LICENSE.txt,
            FONT-LICENSE.txt (Nunito Sans OFL), README.txt
```

### Launcher

1. Data folder `~/Library/Application Support/Advanced Daisenryaku` (override: `AD_USER_DIR`).
2. Is `ad-tr.md` there and exactly the target of the patch (size, CRC32)? Otherwise: ask for the
   JP ROM (file dialog; `AD_ROM=path` instead, for tests), check size and CRC32 against the patch
   (`$100000` bytes, `E0D5E18A`), apply the patch, write `ad-tr.md`. A wrong file gets a message
   and another try. The path picked is noted in `rom-source.txt`: after an update of the app
   (new translation = new patch) the ROM is rebuilt from it without asking again.
3. `settings.ini` from Resources when the data folder has none.
4. Sets `GENESIS_USER_DIR` (the runner's own switch for the data folder, `runner/main.c`),
   `GENESIS_HD_PACK`, `GENESIS_NO_LAUNCHER`; console output to `run.log` when started from
   Finder; then `execv` of `ADRecomp` with the ROM (same process, so the Dock sees one app).
   Arguments are passed on (`--max-frames 600`).

The save game is `ad-tr.srm` in the data folder; `ad-port.ini` there holds the language chosen
in the game, `ad-mapstart.bin` the map start of each save (`saving.md`, "Map start"). To continue a development save:
copy `build/recomp-tr/ad-tr.srm` there.

### No ROM in the app: BPS patch

`tools/bps.py` (create/apply/info) writes the standard BPS format, so the patch also works with
any BPS tool. Size about 1.08 MB: of the 3 MiB target 1,043,618 bytes are read
from the same place in the JP ROM, 17,414 copied from elsewhere in it, 1,047,336 are filler runs and
1,037,360 bytes are in the patch (our routines, strings, glyph cells, repacked intro tiles).
The applier exists twice: Python (`tools/bps.py`) and C (`release/common/rompatch.h`, shared by
the Mac and the Windows launcher); the smoke test compares
the launcher's result with `build/rom/ad-tr.md` byte by byte.

`release.sh` refuses to package when a file in the app has a ROM/save/log name, has `SEGA` at
`$100`, or contains any of 256-byte samples taken every `$4000` from the JP ROM.

### Libraries

Homebrew's `sdl2` is sdl2-compat: `libSDL2-2.0.0.dylib` loads SDL3 at runtime from its own
folder (`@loader_path/libSDL3.dylib` is its first try). Both go to `Contents/Frameworks`; the
game's load command is rewritten to `@executable_path/../Frameworks/…`. Evidence
(`DYLD_PRINT_LIBRARIES=1`): both are loaded from the app, none from `/opt/homebrew`.

## Checks done

- `tools/release.sh` including its smoke test: launcher with `AD_ROM`, scratch data folder,
  600 frames → ROM identical to `build/rom/ad-tr.md`, exit 0, no miss entries.
- By hand, 1500 frames with a screenshot at exit: HD pack loaded from Resources (59666 tiles),
  intro picture rendered, `ad-tr.srm` path in the data folder.
- Through LaunchServices (`open -W --env … --args --max-frames 600`): same result, output in
  `run.log`.
- Wrong ROM (the EN patch) via `AD_ROM`: refused, exit 1, nothing written.

## Limits and packaging details

1. **macOS version:** the app needs macOS 27.2 or newer – the game is built for the build
   machine's version and Homebrew's SDL libraries for 27.0. For older systems: build SDL from
   source with a deployment target and set `CMAKE_OSX_DEPLOYMENT_TARGET`. Apple silicon only.
2. **Signature:** ad hoc (`CODESIGN_IDENTITY` unset). Gatekeeper rejects it on other Macs
   (`spctl`: rejected) until the player right-clicks → Open; a Developer ID and notarization
   need a paid Apple developer account.
3. **Licences:** this repo and the engine are PolyForm Noncommercial 1.0.0 (`LICENSE`,
   `NOTICE.md`); both release scripts ship `LICENSE`, upstream's `PERMISSIONS.md` as
   `PERMISSIONS.txt` and the Nunito Sans OFL as `FONT-LICENSE.txt` (the audit rejects `*.md`).
   Upstream's `RELEASING.md` checklist is met: native target only, no recompiler tool, no
   ROM/saves/logs, trace options off, README with bring-your-own-ROM.
4. **Icon:** 大, the first letter of the 大戦略 title logo, in the logo's colours (stone grey
   `AEAEAE`/`929292`/`777777`, brown 3-D edge `927757`→`573100`, read off the title screen at
   frame 2200), drawn by `tools/make_icon.ps1` (Windows, Yu Gothic Bold):
   - Windows launcher: the letter alone, `release/windows/icon.ico` (16–256 px), embedded by
     `release/windows/launcher.rc`.
   - Mac app (`-Mac`): the letter on a rounded square in the red of the logo's "Advanced"
     banner (`CE0000`→`770000`), Apple's grid (824 of 1024 px, shadow below), as
     `release/macos/AppIcon.iconset` (16–1024 px). `tools/release.sh` makes `AppIcon.icns`
     from it with `iconutil` (a ready `release/macos/AppIcon.icns` is used when there is no
     iconset).
5. **Bundle identifier:** `io.github.hexporter.advanced-daisenryaku` (`BUNDLE_ID=…` overrides);
   keep it stable, macOS keys permissions and preferences on it.
6. Version comes from `project(… VERSION …)` in `recomp/CMakeLists.txt` (0.1.0), the build
   field is `git describe` (`-dirty` with uncommitted changes).
