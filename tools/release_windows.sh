#!/usr/bin/env bash
# Build the Windows version for players: build/release/Advanced Daisenryaku/ (a folder with
# "Advanced Daisenryaku.exe") and a zip of it. Runs on Windows in Git Bash: tools\win release_windows
#   tools/release_windows.sh [--no-hd] [--no-test] [--version X.Y.Z]
# Counterpart of tools/release.sh (Mac app), same rules (docs/notes/release.md): variant tr only, no
# ROM inside – a BPS patch from the JP ROM is applied on the player's PC by the launcher
# (release/windows/launcher.c). The release build is build/release-tr/; build/recomp-tr/ is not touched.
#   --no-hd     leave out the HD text/tile pack (build/hd/pack.bin, made on the Mac)
#   --no-test   skip the smoke test (launcher + game for 600 frames in a scratch data folder)
#   --version   version in README.txt (default: project(VERSION) in recomp/CMakeLists.txt)
# Needs build/rom/ad-tr.md from the Mac (docs/notes/windows.md). Docs: docs/notes/windows.md
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CONFIG=${CONFIG_ENV:-$ROOT/config.env}
[ -f "$CONFIG" ] || { echo "Missing: $CONFIG (cp config.example.env config.env)"; exit 1; }
# shellcheck source=/dev/null
. "$CONFIG"
. "$ROOT/tools/rom_select.sh"
[ "$AD_WINDOWS" = 1 ] || { echo "tools/release_windows.sh runs on Windows (Git Bash, tools\\win release_windows)."; exit 1; }

hd=1 test=1 version=""
while [ $# -gt 0 ]; do
    case "$1" in
        --no-hd)   hd=0; shift ;;
        --no-test) test=0; shift ;;
        --version) version=${2:-}; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 2 ;;
    esac
done
[ -n "$version" ] ||
    version=$(sed -n 's/^project(.* VERSION \([0-9.]*\).*/\1/p' "$ROOT/recomp/CMakeLists.txt")
[ -n "$version" ] || { echo "No version found (--version X.Y.Z)"; exit 1; }
build=$(git -C "$ROOT" describe --always --dirty 2>/dev/null || echo unknown)
case "$build" in *-dirty) echo "NOTE: uncommitted changes – the build is marked '$build'." ;; esac

APP_NAME="Advanced Daisenryaku"
SRC="$ROOT/release/windows"
OUT="$ROOT/build/release"
DIR="$OUT/$APP_NAME"
STAGE="$ROOT/build/release-tr"

echo "> Release build of the game and the launcher (tr)"
"$ROOT/tools/build.sh" --rom tr --release | tail -4
rom_select jp && rom_verify
JP_ROM=$ROM_FILE
TR_ROM="$ROOT/build/rom/ad-tr.md"

echo "> Translation patch"
"$PYTHON" "$ROOT/tools/bps.py" create "$JP_ROM" "$TR_ROM" "$STAGE/translation.bps"

echo "> Folder"
# Only the folder of this script is replaced; refuse anything else at that path.
if [ -e "$DIR" ]; then
    [ -f "$DIR/ADRecomp.exe" ] || { echo "Not a release folder, not replacing: $DIR"; exit 1; }
    rm -rf "$DIR"
fi
mkdir -p "$DIR"
cp "$STAGE/ADRecomp.exe" "$STAGE/SDL2.dll" "$DIR/"
cp "$STAGE/ADLauncher.exe" "$DIR/$APP_NAME.exe"
cp "$STAGE/translation.bps" "$ROOT/recomp/game/settings.ini" "$DIR/"
cp "${RECOMPILER_DIR:?}/LICENSE.md" "$DIR/LICENSE"
cp "$RECOMPILER_DIR/THIRD-PARTY-LICENSES.md" "$DIR/"
cp "$RECOMPILER_DIR/PERMISSIONS.md" "$DIR/PERMISSIONS.txt"
cp "$ROOT/tools/hd/fonts/OFL.txt" "$DIR/FONT-LICENSE.txt"
for f in "$RECOMPILER_DIR"/runner/external/SDL2/SDL2-*/COPYING.txt; do cp "$f" "$DIR/SDL-LICENSE.txt"; done
if [ "$hd" = 1 ]; then
    [ -f "$ROOT/build/hd/pack.bin" ] ||
        { echo "HD pack missing: build/hd/pack.bin (copy it from the Mac, or --no-hd)"; exit 1; }
    cp "$ROOT/build/hd/pack.bin" "$DIR/pack.bin"
fi
sed -e "s/@VERSION@/$version/g" -e "s/@BUILD@/$build/g" "$SRC/README.txt" > "$DIR/README.txt"

echo "> Audit: no ROM, save game or log in the folder"
bad=$(find "$DIR" -type f \( -name '*.md' -o -name '*.gen' -o -name '*.smd' -o -name '*.srm' \
        -o -name '*.log' -o -name '*.toml' -o -name 'native_save_*' -o -name 'ramdump*' \
        -o -name 'GenesisRecomp*' -o -name '*.pdb' -o -name 'debug.ini' \) \
        ! -name 'THIRD-PARTY-LICENSES.md')
# A Mega Drive ROM has "SEGA" at $100; the original ROM data must not be inside any file either.
"$PYTHON" - "$JP_ROM" "$DIR" <<'PY' || bad="$bad"$'\n'"(ROM data found, see above)"
import os, sys
rom = open(sys.argv[1], "rb").read()
probes = [rom[o:o + 256] for o in range(0x200, len(rom) - 256, 0x4000)]
probes = [p for p in probes if len(set(p)) > 16]          # skip filler
hit = 0
for d, _, files in os.walk(sys.argv[2]):
    for name in files:
        path = os.path.join(d, name)
        data = open(path, "rb").read()
        if data[0x100:0x104] == b"SEGA":
            print(f"  {path}: looks like a Mega Drive ROM"); hit = 1
        n = sum(p in data for p in probes)
        if n:
            print(f"  {path}: {n} of {len(probes)} samples of the original ROM"); hit = 1
sys.exit(hit)
PY
[ -z "$bad" ] || { echo "Refusing to package, found:"; echo "$bad"; exit 1; }

if [ "$test" = 1 ]; then
    echo "> Smoke test (600 frames, scratch data folder)"
    if tasklist //FI "IMAGENAME eq ADRecomp.exe" 2>/dev/null | grep -qi ADRecomp; then
        echo "A game instance is running – smoke test skipped (close it, or pass --no-test)."
        exit 1
    fi
    scratch=$(cygpath -m "$(mktemp -d)")
    rc=0
    AD_USER_DIR="$scratch" AD_ROM="$JP_ROM" "$DIR/$APP_NAME.exe" --max-frames 600 \
        > "$STAGE/smoke.log" 2>&1 || rc=$?
    [ "$rc" = 0 ] && grep -q '^\[DONE\] 600 frames' "$STAGE/smoke.log" ||
        { echo "Smoke test failed (exit $rc), see $STAGE/smoke.log and $scratch"; exit 1; }
    cmp -s "$scratch/ad-tr.md" "$TR_ROM" ||
        { echo "Patched ROM differs from build/rom/ad-tr.md, see $scratch"; exit 1; }
    for f in dispatch_misses interior_label_misses floor_unsafe; do
        grep -q '^# entries: *0$' "$scratch/$f.toml" ||
            { echo "Smoke test: entries in $f.toml (or file missing), see $scratch"; exit 1; }
    done
    echo "ok: ROM patched identically, 600 frames, no misses ($STAGE/smoke.log)"
    rm -rf "$scratch"
fi

zip="$OUT/AdvancedDaisenryaku-$version-windows-x64.zip"
[ -f "$zip" ] && rm -f "$zip"
(cd "$OUT" && "$PYTHON" -m zipfile -c "$(basename "$zip")" "$APP_NAME")
echo
echo "OK: $DIR"
echo "    $zip ($(du -h "$zip" | cut -f1 | tr -d ' '), version $version, build $build)"
echo "Start as a player would: double-click \"$DIR/$APP_NAME.exe\""
