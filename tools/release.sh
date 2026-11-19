#!/usr/bin/env bash
# Build the Mac app for players: build/release/Advanced Daisenryaku.app and a zip of it.
#   tools/release.sh [--no-hd] [--no-test] [--version X.Y.Z]
# Variant tr only (our translation). The app contains no ROM: it carries a BPS patch from the JP
# ROM to the translated one and applies it on the player's Mac (release/macos/launcher.c).
# Everything happens in build/release-tr/ (release build of the game, tools/build.sh --release)
# and build/release/ (the app); the development build in build/recomp-tr/ is not touched.
#   --no-hd     leave out the HD text/tile pack (build/hd/pack.bin)
#   --no-test   skip the smoke test (start of the finished app for 600 frames in a scratch folder)
#   --version   version shown in Finder (default: project(VERSION) in recomp/CMakeLists.txt)
# Environment: BUNDLE_ID (default io.github.hexporter.advanced-daisenryaku), CODESIGN_IDENTITY (default "-",
# ad hoc). Docs: docs/notes/release.md
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CONFIG=${CONFIG_ENV:-$ROOT/config.env}
[ -f "$CONFIG" ] || { echo "Missing: $CONFIG (cp config.example.env config.env)"; exit 1; }
# shellcheck source=/dev/null
. "$CONFIG"
. "$ROOT/tools/rom_select.sh"
[ "$(uname -s)" = Darwin ] || { echo "tools/release.sh builds the Mac app and needs macOS."; exit 1; }

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
BUNDLE_ID=${BUNDLE_ID:-io.github.hexporter.advanced-daisenryaku}
SIGN=${CODESIGN_IDENTITY:--}
SRC="$ROOT/release/macos"
OUT="$ROOT/build/release"
APP="$OUT/$APP_NAME.app"
STAGE="$ROOT/build/release-tr"

echo "> Release build of the game (tr)"
"$ROOT/tools/build.sh" --rom tr --release | tail -4
GAME="$STAGE/ADRecomp"
rom_select jp && rom_verify
JP_ROM=$ROM_FILE
TR_ROM="$ROOT/build/rom/ad-tr.md"

echo "> Translation patch"
"$ROOT/tools/bps.py" create "$JP_ROM" "$TR_ROM" "$STAGE/translation.bps"

echo "> App bundle"
# Only the app of this script is replaced; refuse anything else at that path.
if [ -e "$APP" ]; then
    [ -f "$APP/Contents/Info.plist" ] || { echo "Not an app bundle, not replacing: $APP"; exit 1; }
    rm -rf "$APP"
fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Frameworks"
cp "$GAME" "$APP/Contents/MacOS/ADRecomp"
clang -O2 -Wall -Wextra -arch arm64 -mmacosx-version-min="${MACOS_MIN:-11.0}" -o "$APP/Contents/MacOS/$APP_NAME" "$SRC/launcher.c"

# Libraries outside the system (SDL from Homebrew) go into Contents/Frameworks.
# sdl2-compat loads SDL3 at runtime from its own folder (@loader_path/libSDL3.dylib).
min_macos=$(vtool -show-build "$GAME" | awk '$1 == "minos" {print $2}')
bundle_lib() {   # $1 = library path, $2 = name in Frameworks
    cp -L "$1" "$APP/Contents/Frameworks/$2"
    chmod u+w "$APP/Contents/Frameworks/$2"
    install_name_tool -id "@rpath/$2" "$APP/Contents/Frameworks/$2" 2>/dev/null
    local m; m=$(vtool -show-build "$1" | awk '$1 == "minos" {print $2}')
    # the newest requirement of all parts decides
    if [ "$(printf '%s\n%s\n' "$m" "$min_macos" | sort -V | tail -1)" = "$m" ]; then min_macos=$m; fi
}
{ otool -L "$GAME" | awk 'NR > 1 {print $1}' | grep -v -e '^/usr/lib/' -e '^/System/' || true; } \
    > "$STAGE/bundle-libs.txt"
while read -r lib; do
    name=$(basename "$lib")
    bundle_lib "$lib" "$name"
    install_name_tool -change "$lib" "@executable_path/../Frameworks/$name" \
        "$APP/Contents/MacOS/ADRecomp" 2>/dev/null
    case "$name" in libSDL2*)
        if strings "$lib" | grep -q 'libSDL3'; then
            sdl3=$(brew --prefix sdl3)/lib/libSDL3.dylib
            [ -f "$sdl3" ] || { echo "sdl2-compat needs SDL3, not found: $sdl3"; exit 1; }
            bundle_lib "$sdl3" libSDL3.dylib
            cp "$(brew --prefix sdl3)/LICENSE.txt" "$APP/Contents/Resources/SDL-LICENSE.txt"
        else
            # plain SDL2 (tools/sdl2_macos.sh): share/licenses/SDL2/LICENSE.txt in its prefix
            prefix=$(dirname "$(dirname "$(realpath "$lib")")")
            for f in "$prefix/share/licenses/SDL2/LICENSE.txt" "$prefix/LICENSE.txt" ""; do
                [ -z "$f" ] && { echo "SDL licence not found next to $lib"; exit 1; }
                [ -f "$f" ] && { cp "$f" "$APP/Contents/Resources/SDL-LICENSE.txt"; break; }
            done
        fi ;;
    esac
done < "$STAGE/bundle-libs.txt"

cp "$STAGE/translation.bps" "$ROOT/recomp/game/settings.ini" "$APP/Contents/Resources/"
cp "${RECOMPILER_DIR:?}/LICENSE.md" "$APP/Contents/Resources/LICENSE"
cp "$RECOMPILER_DIR/THIRD-PARTY-LICENSES.md" "$APP/Contents/Resources/"
cp "$RECOMPILER_DIR/PERMISSIONS.md" "$APP/Contents/Resources/PERMISSIONS.txt"
cp "$ROOT/tools/hd/fonts/OFL.txt" "$APP/Contents/Resources/FONT-LICENSE.txt"
if [ "$hd" = 1 ]; then
    [ -f "$ROOT/build/hd/pack.bin" ] ||
        { echo "HD pack missing: build/hd/pack.bin (tools/hdpack.py build, or --no-hd)"; exit 1; }
    cp "$ROOT/build/hd/pack.bin" "$APP/Contents/Resources/pack.bin"
fi
# App icon: release/macos/AppIcon.iconset (tools/make_icon.ps1 -Mac) → AppIcon.icns with iconutil;
# a ready AppIcon.icns in release/macos/ is used as it is.
icon=""
if [ -d "$SRC/AppIcon.iconset" ]; then
    iconutil -c icns "$SRC/AppIcon.iconset" -o "$STAGE/AppIcon.icns"   # set -e: stops on an error
    icon="$STAGE/AppIcon.icns"
elif [ -f "$SRC/AppIcon.icns" ]; then
    icon="$SRC/AppIcon.icns"
fi
[ -n "$icon" ] && cp "$icon" "$APP/Contents/Resources/AppIcon.icns"
fill() { sed -e "s/@VERSION@/$version/g" -e "s/@BUILD@/$build/g" \
             -e "s/@BUNDLE_ID@/$BUNDLE_ID/g" -e "s/@MIN_MACOS@/$min_macos/g" "$1"; }
fill "$SRC/Info.plist.in" > "$APP/Contents/Info.plist"
[ -n "$icon" ] &&
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AppIcon" "$APP/Contents/Info.plist"
fill "$SRC/README.txt" > "$APP/Contents/Resources/README.txt"
plutil -lint "$APP/Contents/Info.plist" >/dev/null

echo "> Audit: no ROM, save game or log in the app"
bad=$(find "$APP" -type f \( -name '*.md' -o -name '*.gen' -o -name '*.smd' -o -name '*.srm' \
        -o -name '*.log' -o -name '*.toml' -o -name 'native_save_*' -o -name 'ramdump*' \) \
        ! -name 'THIRD-PARTY-LICENSES.md')
# A Mega Drive ROM has "SEGA" at $100; the original ROM data must not be inside any file either.
python3 - "$JP_ROM" "$APP" <<'PY' || bad="$bad"$'\n'"(ROM data found, see above)"
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

echo "> Sign ($([ "$SIGN" = - ] && echo "ad hoc" || echo "$SIGN"))"
for f in "$APP"/Contents/Frameworks/*; do codesign --force -s "$SIGN" "$f" 2>/dev/null; done
codesign --force -s "$SIGN" "$APP/Contents/MacOS/ADRecomp" 2>/dev/null
codesign --force -s "$SIGN" "$APP" 2>/dev/null
codesign --verify --deep --strict "$APP"

if [ "$test" = 1 ]; then
    echo "> Smoke test (600 frames, scratch data folder)"
    if pgrep -f ADRecomp >/dev/null; then
        echo "A game instance is running – smoke test skipped (close it, or pass --no-test)."
        exit 1
    fi
    scratch=$(mktemp -d)
    # Without a terminal the launcher writes the console output to run.log in the data folder.
    rc=0
    AD_USER_DIR="$scratch" AD_ROM="$JP_ROM" "$APP/Contents/MacOS/$APP_NAME" \
        --max-frames 600 > /dev/null 2>&1 || rc=$?
    cp "$scratch/run.log" "$STAGE/smoke.log" 2>/dev/null || true
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

zip="$OUT/AdvancedDaisenryaku-$version-mac-arm64.zip"
[ -f "$zip" ] && rm -f "$zip"
ditto -c -k --keepParent "$APP" "$zip"
echo
echo "OK: $APP"
echo "    $zip ($(du -h "$zip" | cut -f1 | tr -d ' '), version $version, build $build, macOS >= $min_macos)"
echo "Start as a player would: open \"$APP\""
