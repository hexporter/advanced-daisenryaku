#!/usr/bin/env bash
# Build SDL2 from source for the Mac release, so the app runs on older macOS than the build machine.
#   tools/sdl2_macos.sh [--force]
# Homebrew's sdl2 is built for the newest macOS only (and is sdl2-compat, which needs SDL3 too);
# this builds plain SDL2 with a deployment target of MACOS_MIN (default 11.0, the first macOS on
# Apple silicon) into build/sdl2-macos/. tools/build.sh --release uses it on the Mac; the
# development build keeps Homebrew's SDL. Docs: docs/notes/release.md ("macOS version").
#   --force   build again even when build/sdl2-macos/ is current
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ "$(uname -s)" = Darwin ] || { echo "tools/sdl2_macos.sh is for macOS."; exit 1; }

SDL_VERSION=2.32.10
SDL_SHA256=5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165
MACOS_MIN=${MACOS_MIN:-11.0}
SRC_DIR="$ROOT/build/sdl2-src"
TARBALL="$SRC_DIR/dl/SDL2-$SDL_VERSION.tar.gz"
PREFIX="$ROOT/build/sdl2-macos"
STAMP="$PREFIX/.built"
want="SDL2 $SDL_VERSION macOS $MACOS_MIN arm64"

force=0
[ "${1:-}" = --force ] && force=1
if [ "$force" = 0 ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$want" ]; then
    echo "SDL2 current: $PREFIX ($want)"
    exit 0
fi

mkdir -p "$SRC_DIR/dl"
if [ ! -f "$TARBALL" ]; then
    echo "> Download SDL2-$SDL_VERSION.tar.gz (github.com/libsdl-org/SDL)"
    curl -fL -o "$TARBALL" \
        "https://github.com/libsdl-org/SDL/releases/download/release-$SDL_VERSION/SDL2-$SDL_VERSION.tar.gz"
fi
echo "$SDL_SHA256  $TARBALL" | shasum -a 256 -c - >/dev/null ||
    { echo "SHA-256 mismatch: $TARBALL"; exit 1; }
rm -rf "$SRC_DIR/SDL2-$SDL_VERSION"
tar -xzf "$TARBALL" -C "$SRC_DIR"

echo "> Build $want"
rm -rf "$PREFIX" "$SRC_DIR/build"
# The install name is the absolute path in $PREFIX (as with Homebrew); tools/release.sh rewrites it.
cmake -S "$SRC_DIR/SDL2-$SDL_VERSION" -B "$SRC_DIR/build" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
      -DCMAKE_INSTALL_NAME_DIR="$PREFIX/lib" \
      -DCMAKE_OSX_DEPLOYMENT_TARGET="$MACOS_MIN" -DCMAKE_OSX_ARCHITECTURES=arm64 \
      -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TEST=OFF >/dev/null
ninja -C "$SRC_DIR/build" install >/dev/null
lib="$PREFIX/lib/libSDL2-2.0.0.dylib"
minos=$(vtool -show-build "$lib" | awk '$1 == "minos" {print $2}')
[ "$minos" = "$MACOS_MIN" ] || { echo "Unexpected minos $minos in $lib"; exit 1; }
echo "$want" > "$STAMP"
echo "SDL2 built: $PREFIX (minos $minos)"
