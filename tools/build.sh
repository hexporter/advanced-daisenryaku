#!/usr/bin/env bash
# Build the game: generate C code from ROM + recomp/game/game.toml and compile the runner.
#   tools/build.sh [--rom jp|en|tr] [--clean] [--release]
# tr: first generates build/rom/ad-tr.md from the JP ROM and translation/ (tools/translate_rom.py).
# Without --rom, ROM_VARIANT from config.env applies (default jp).
# Result: build/recomp-<variant>/ADRecomp. Start: tools/run.sh [--rom jp|en|tr]
# --release: same sources without the debug server and the reverse-debug ring, in its own folder
# build/release-<variant>/ (the development build, its save games and evidence stay untouched).
# Used by tools/release.sh; not meant to be started with run.sh.
# Windows: runs in Git Bash with the MSVC environment (tools/build.ps1 sets it up); the tr ROM is
# made on the Mac (the typeface needs CoreText) – without swift an existing build/rom/ad-tr.md is
# used as it is (docs/notes/windows.md).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CONFIG=${CONFIG_ENV:-$ROOT/config.env}
[ -f "$CONFIG" ] || { echo "Missing: $CONFIG (cp config.example.env config.env)"; exit 1; }
# shellcheck source=/dev/null
. "$CONFIG"
. "$ROOT/tools/rom_select.sh"
: "${RECOMPILER_DIR:?RECOMPILER_DIR missing in config.env}"

variant="" clean=0 release=0
while [ $# -gt 0 ]; do
    case "$1" in
        --rom)   variant=${2:-}; shift 2 ;;
        --clean) clean=1; shift ;;
        --release) release=1; shift ;;
        *) echo "Unknown argument: $1"; exit 2 ;;
    esac
done
rom_select "$variant"
if [ "$ROM_VARIANT" = tr ]; then
    if command -v swift >/dev/null || [ ! -f "$ROM_FILE" ]; then
        "$PYTHON" "$ROOT/tools/translate_rom.py" "${ROM_JP_PATH:?ROM_JP_PATH missing in config.env}" "$ROM_FILE"
    else
        # No CoreText here (Windows): the translated ROM comes from the Mac (docs/notes/windows.md).
        echo "NOTE: no swift – using build/rom/ad-tr.md as it is (made on the Mac), translation not rebuilt."
    fi
    ROM_CRC32=$(rom_crc32)
fi
rom_verify
[ "$release" = 1 ] && ROM_BUILD="$ROOT/build/release-$ROM_VARIANT"

# Apply our framework patches (recomp/patches/), then check the state.
"$ROOT/tools/recompiler_update.sh" patch
"$ROOT/tools/recompiler_update.sh" check >/dev/null ||
    echo "WARNING: recompiler checkout differs from the pin ('tools/recompiler_update.sh check')."

# --clean: empty the build folder, keep save games (*.srm, next to the binary), save states and settings.
if [ "$clean" = 1 ] && [ -d "$ROM_BUILD" ]; then
    keep=$(mktemp -d)
    find "$ROM_BUILD" -maxdepth 1 \( -name '*.srm' -o -name 'native_save_*.bin' -o -name settings.ini \) -exec mv {} "$keep"/ \;
    rm -rf "$ROM_BUILD" && mkdir -p "$ROM_BUILD"
    find "$keep" -type f -exec mv {} "$ROM_BUILD"/ \;
    rmdir "$keep"
fi

# Generation expects the ROM in the game folder; one symlink per variant (excluded via .gitignore).
# Windows: a copy (symlinks need developer mode there).
if [ "$AD_WINDOWS" = 1 ]; then cp -f "$ROM_FILE" "$ROOT/recomp/game/ad-$ROM_VARIANT.bin"
else ln -sfn "$ROM_FILE" "$ROOT/recomp/game/ad-$ROM_VARIANT.bin"; fi

flags=""
# macOS: _POSIX_C_SOURCE in engine files otherwise hides BSD definitions (docs/notes/recompiler.md)
[ "$(uname -s)" = Darwin ] && flags="-DCMAKE_C_FLAGS=-D_DARWIN_C_SOURCE"
# Windows: MSVC (cl from the developer environment, tools/build.ps1), never a stray gcc
[ "$AD_WINDOWS" = 1 ] && flags="-DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl"
# Always passed, so that a build folder never keeps a stale value in its CMake cache.
if [ "$release" = 1 ]; then flags="$flags -DGEN_ENABLE_TRACE=OFF -DSONIC_REVERSE_DEBUG=OFF"
else flags="$flags -DGEN_ENABLE_TRACE=ON -DSONIC_REVERSE_DEBUG=ON"; fi

cmake -S "$ROOT/recomp" -B "$ROM_BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DGENESIS_RECOMP_ROOT="$RECOMPILER_DIR" \
      -DAD_ROM_VARIANT="$ROM_VARIANT" -DAD_ROM_CRC32="0x$ROM_CRC32" -DAD_ROM_SIZE="$ROM_SIZE" $flags
targets=ADRecomp
# Windows release: also the launcher (release/windows/launcher.c, packaged by tools/release_windows.sh)
[ "$AD_WINDOWS" = 1 ] && [ "$release" = 1 ] && targets="$targets ADLauncher"
ninja -C "$ROM_BUILD" $targets

# Runner settings (controller layout, docs/notes/controls.md); never overwrite a changed one.
[ "$release" = 1 ] || [ -f "$ROM_BUILD/settings.ini" ] || cp "$ROOT/recomp/game/settings.ini" "$ROM_BUILD/settings.ini"

echo
echo "OK ($ROM_VARIANT): $ROM_BUILD/ADRecomp$EXE"
echo "Generation logs: $ROM_BUILD/generated/ad/"
if [ "$release" = 1 ]; then echo "Package: tools/release.sh (Windows: tools/release_windows.sh)"
else echo "Start: tools/run.sh --rom $ROM_VARIANT"; fi
