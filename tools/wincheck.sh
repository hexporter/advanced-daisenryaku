#!/usr/bin/env bash
# Compile check for Windows on the Mac: cross-builds ADRecomp.exe and the launcher (ADLauncher.exe)
# with mingw-w64 (brew install mingw-w64) into build/wincheck-<variant>/. GCC, not MSVC – it finds
# POSIX calls and missing #ifdef _WIN32 branches, not MSVC-only problems. The result is not meant
# to be played (no manifest, mingw runtime DLLs missing). Docs: docs/notes/windows.md
#   tools/wincheck.sh [--rom jp|en|tr]          (default: ROM_VARIANT from config.env)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CONFIG=${CONFIG_ENV:-$ROOT/config.env}
[ -f "$CONFIG" ] || { echo "Missing: $CONFIG (cp config.example.env config.env)"; exit 1; }
# shellcheck source=/dev/null
. "$CONFIG"
. "$ROOT/tools/rom_select.sh"
: "${RECOMPILER_DIR:?RECOMPILER_DIR missing in config.env}"

variant=""
while [ $# -gt 0 ]; do
    case "$1" in
        --rom) variant=${2:-}; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 2 ;;
    esac
done
command -v x86_64-w64-mingw32-gcc >/dev/null || { echo "Needs mingw-w64: brew install mingw-w64"; exit 1; }
rom_select "$variant"
[ -f "$ROM_FILE" ] || { echo "ROM not found: $ROM_FILE (tools/build.sh --rom $ROM_VARIANT first)"; exit 1; }
[ -n "$ROM_CRC32" ] || ROM_CRC32=$(rom_crc32)
RECOMP="$RECOMPILER_DIR/build/recompiler/GenesisRecomp"
[ -x "$RECOMP" ] || { echo "GenesisRecomp not built: tools/recompiler_update.sh sync"; exit 1; }
# the generation reads the ROM from the game folder, as in build.sh
ln -sfn "$ROM_FILE" "$ROOT/recomp/game/ad-$ROM_VARIANT.bin"
"$ROOT/tools/recompiler_update.sh" patch >/dev/null

OUT="$ROOT/build/wincheck-$ROM_VARIANT"
mkdir -p "$OUT"
cat > "$OUT/mingw.cmake" <<'EOF'
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER x86_64-w64-mingw32-gcc)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)
set(CMAKE_RC_COMPILER x86_64-w64-mingw32-windres)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)
EOF
# The host recompiler generates the C code (GENESIS_RECOMPILER_EXE, the framework's cross-build switch).
cmake -S "$ROOT/recomp" -B "$OUT" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_TOOLCHAIN_FILE="$OUT/mingw.cmake" -DGENESIS_RECOMPILER_EXE="$RECOMP" \
      -DGENESIS_RECOMP_ROOT="$RECOMPILER_DIR" \
      -DAD_ROM_VARIANT="$ROM_VARIANT" -DAD_ROM_CRC32="0x$ROM_CRC32" -DAD_ROM_SIZE="$ROM_SIZE" \
      -DGEN_ENABLE_TRACE=OFF -DSONIC_REVERSE_DEBUG=OFF >/dev/null
ninja -C "$OUT" ADRecomp ADLauncher
echo
echo "OK: $OUT/ADRecomp.exe and ADLauncher.exe compile and link for Windows (mingw-w64)."
