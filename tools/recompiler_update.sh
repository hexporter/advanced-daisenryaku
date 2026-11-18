#!/usr/bin/env bash
# Keep the recompiler (segagenesisrecomp) on a fixed commit and update it deliberately.
# Pin: recomp/RECOMPILER_COMMIT. Docs: tools/README.md, docs/notes/recompiler.md
#
#   tools/recompiler_update.sh check            compare pin vs. checkout
#   tools/recompiler_update.sh sync             set the checkout to the pin and build
#   tools/recompiler_update.sh test             framework tests at the current state
#   tools/recompiler_update.sh patch            apply our patches (recomp/patches/*.patch)
#   tools/recompiler_update.sh update [REF]     raise to REF (default: origin/HEAD = default branch),
#                                               build, test; ok -> commit the pin,
#                                               error -> back to the old pin
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CONFIG=${CONFIG_ENV:-$ROOT/config.env}
PIN_FILE="$ROOT/recomp/RECOMPILER_COMMIT"

[ -f "$CONFIG" ] || { echo "Missing: $CONFIG (cp config.example.env config.env)"; exit 1; }
# shellcheck source=/dev/null
. "$CONFIG"
. "$ROOT/tools/rom_select.sh"     # also AD_WINDOWS, EXE (Git Bash on Windows)
: "${RECOMPILER_DIR:?RECOMPILER_DIR missing in config.env}"
[ -d "$RECOMPILER_DIR/.git" ] || { echo "Not a git checkout: $RECOMPILER_DIR"; exit 1; }
[ -f "$PIN_FILE" ] || { echo "Missing: $PIN_FILE"; exit 1; }

PIN=$(tr -d '[:space:]' < "$PIN_FILE")
RG() { git -C "$RECOMPILER_DIR" "$@"; }
# Apple clang defaults to C++98; ymfm needs >= C++11 (docs/notes/recompiler.md)
CMAKE_FLAGS="-DCMAKE_CXX_STANDARD=17"
# macOS: _POSIX_C_SOURCE in runner/cd/debug.c otherwise hides INADDR_LOOPBACK
[ "$(uname -s)" = Darwin ] && CMAKE_FLAGS="$CMAKE_FLAGS -DCMAKE_C_FLAGS=-D_DARWIN_C_SOURCE"
# Windows: MSVC from the developer environment (tools/build.ps1); the framework's bundled SDL2
# VC package for the tests (find_package(SDL2 CONFIG))
if [ "$AD_WINDOWS" = 1 ]; then
    CMAKE_FLAGS="$CMAKE_FLAGS -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl"
    for d in "$RECOMPILER_DIR"/runner/external/SDL2/SDL2-*/; do
        CMAKE_FLAGS="$CMAKE_FLAGS -DCMAKE_PREFIX_PATH=${d%/}"
    done
fi
short() { printf '%.7s' "$1"; }
# host_stream_exit_1_1: segfaults in about 2 of 3 runs at 76490c6 (host writer exit drain; no file
# of ours involved). ctest -E regex; override with FLAKY_TESTS='^$' to run everything.
# Windows also leaves out two upstream tests that assume the author's setup, not a code problem:
# disasm_inline_tables (gen_disasm_jumptables.py needs its checkout five folders deep:
# Path(__file__).parents[5]) and segacd_register_span_catalog (expects Release/flow.exe of a
# Visual Studio generator; we build with Ninja).
if [ "$AD_WINDOWS" = 1 ]; then
    FLAKY_TESTS=${FLAKY_TESTS:-'^(host_stream_exit_1_1|disasm_inline_tables|segacd_register_span_catalog)$'}
else
    FLAKY_TESTS=${FLAKY_TESTS:-'^host_stream_exit_1_1$'}
fi

# Our own fixes to the framework are patches in recomp/patches/ (sorted, as a stack).
# After applying, the total diff is stored as a stamp in the recompiler's .git folder;
# from it the script recognises "stack active" and can revert it exactly, even when
# patches overlap (e.g. size checks in rb_state.c).
PATCH_DIR="$ROOT/recomp/patches"
STAMP_DIFF="$RECOMPILER_DIR/.git/ad-patches.diff"
STAMP_SET="$RECOMPILER_DIR/.git/ad-patches.set"
patch_list() { ls "$PATCH_DIR"/*.patch 2>/dev/null | sort || true; }
patchset_id() {
    local l; l=$(patch_list)
    if [ -z "$l" ]; then echo none; return; fi
    if command -v shasum >/dev/null; then cat $l | shasum -a 256 | cut -d' ' -f1
    else cat $l | sha256sum | cut -d' ' -f1; fi
}
work_diff() { RG diff --ignore-submodules; }
# clean | applied | foreign
patch_state() {
    if [ -z "$(work_diff)" ]; then echo clean; return; fi
    if [ -f "$STAMP_DIFF" ] && cmp -s <(work_diff) "$STAMP_DIFF"; then echo applied; return; fi
    echo foreign
}
patches_applied() {
    [ "$(patch_state)" = applied ] && [ "$(cat "$STAMP_SET" 2>/dev/null)" = "$(patchset_id)" ]
}
patches_revert() {
    case "$(patch_state)" in
        applied) RG apply -R "$STAMP_DIFF" && rm -f "$STAMP_DIFF" "$STAMP_SET" &&
                 echo "> Patches reverted" ;;
        clean)   rm -f "$STAMP_DIFF" "$STAMP_SET" ;;
        foreign) ;;   # require_clean/check report this
    esac
}
patches_apply() {
    patches_applied && return 0
    patches_revert
    [ "$(patch_state)" = clean ] || {
        echo "Recompiler checkout has foreign changes, patches not applied:"
        RG status --short --untracked-files=no; return 1; }
    local p
    for p in $(patch_list); do
        if ! RG apply "$p"; then
            echo "Patch does not apply: $(basename "$p") – resetting the checkout"
            RG checkout -- . ; return 1
        fi
        echo "> Patch applied: $(basename "$p")"
    done
    if [ -n "$(patch_list)" ]; then work_diff > "$STAMP_DIFF"; patchset_id > "$STAMP_SET"; fi
}

require_clean() {
    patches_revert
    if [ -n "$(RG status --porcelain --untracked-files=no)" ]; then
        echo "Recompiler checkout has local changes, aborting:"
        RG status --short --untracked-files=no
        exit 1
    fi
}

checkout() {   # $1 = commit
    echo "> checkout $(short "$1")"
    RG -c advice.detachedHead=false checkout -q "$1" &&
    RG submodule update --init --recursive -q &&
    patches_apply
}

build() {
    echo "> Building the recompiler"
    cmake -S "$RECOMPILER_DIR/recompiler" -B "$RECOMPILER_DIR/build/recompiler" \
          -G Ninja -DCMAKE_BUILD_TYPE=Release $CMAKE_FLAGS >/dev/null &&
    ninja -C "$RECOMPILER_DIR/build/recompiler"
}

tests() {
    echo "> Framework tests (ROM-independent)"
    cmake -S "$RECOMPILER_DIR/tests" -B "$RECOMPILER_DIR/build/tests" \
          -G Ninja -DCMAKE_BUILD_TYPE=Release $CMAKE_FLAGS >/dev/null &&
    ninja -k 0 -C "$RECOMPILER_DIR/build/tests" &&
    # macOS: /var -> /private/var; tests compare resolved with unresolved temp paths
    # FLAKY_TESTS: upstream tests that fail at random on macOS, left out (docs/notes/recompiler.md).
    if [ "$AD_WINDOWS" = 1 ]; then
        # SDL2.dll from the VC package on PATH (as /c/…: the colon of C:/… would split PATH in
        # Git Bash). %TEMP% in its long form: with a user name over 8 letters it is an 8.3 path
        # (ADMINI~1), and tests compare it with resolved paths.
        local sdl tmp
        sdl=$(cygpath -u "$(ls -d "$RECOMPILER_DIR"/runner/external/SDL2/SDL2-*/lib/x64 | head -n 1)")
        tmp=$(cygpath -law "${TEMP:-/tmp}")
        PATH="$sdl:$PATH" TEMP="$tmp" TMP="$tmp" TMPDIR="$tmp" \
            ctest --test-dir "$RECOMPILER_DIR/build/tests" --output-on-failure -E "$FLAKY_TESTS"
    else
        TMPDIR=$(cd "${TMPDIR:-/tmp}" && pwd -P) \
            ctest --test-dir "$RECOMPILER_DIR/build/tests" --output-on-failure -E "$FLAKY_TESTS"
    fi
}

generate() {
    local toml="$ROOT/recomp/game/game.toml"
    if [ ! -f "$toml" ]; then
        echo "> Generation skipped (recomp/game.toml missing)"
        return 0
    fi
    # Generation probe always with the JP original (the code is the same in both variants).
    . "$ROOT/tools/rom_select.sh"
    rom_select jp && rom_verify || return 1
    echo "> Generating C code (probe, JP)"
    local out="$ROOT/build/generate-probe"
    rm -rf "$out" && mkdir -p "$out"
    (cd "$ROOT/recomp/game" &&
     "$RECOMPILER_DIR/build/recompiler/GenesisRecomp$EXE" "$ROM_FILE" \
         --game "$toml" --output-dir "$out" > "$out/generate.log" 2>&1) ||
        { echo "Generation failed, see $out/generate.log"; return 1; }
    grep -E "Final function count|TOTAL" "$out/generate.log" || true
}

cmd_check() {
    local head; head=$(RG rev-parse HEAD)
    echo "Pin:      $PIN"
    echo "Checkout: $head"
    if [ "$head" != "$PIN" ]; then
        echo "MISMATCH – 'tools/recompiler_update.sh sync' sets the checkout to the pin."
        return 1
    fi
    case "$(patch_state)" in
        foreign)
            echo "WARNING: local changes in the recompiler checkout that do not come from recomp/patches/."
            return 1 ;;
        applied)
            if patches_applied; then
                echo "Patches active: $(patch_list | xargs -r -n1 basename | tr '\n' ' ')"
            else
                echo "NOTE: outdated patch stack active ('tools/recompiler_update.sh patch')."
            fi ;;
        clean)
            [ -n "$(patch_list)" ] &&
                echo "NOTE: patches not applied ('tools/recompiler_update.sh patch')." ;;
    esac
    [ -x "$RECOMPILER_DIR/build/recompiler/GenesisRecomp$EXE" ] ||
        { echo "WARNING: GenesisRecomp not built yet ('sync')."; return 1; }
    echo "OK"
}

cmd_sync() {
    require_clean
    checkout "$PIN" && build
}

cmd_update() {
    local ref=${1:-origin/HEAD} new
    require_clean
    echo "> fetch"
    # No --tags: upstream rewrote its history (07.11.2026) and moved the tags; forcing them would
    # fail ("would clobber existing tag"), and the old tags keep the old pins reachable locally.
    RG fetch -q origin
    new=$(RG rev-parse "$ref^{commit}")
    if [ "$new" = "$PIN" ]; then
        echo "Already up to date: $(short "$PIN")"
        return 0
    fi
    echo "New commits $(short "$PIN")..$(short "$new"): $(RG rev-list --count "$PIN..$new")"
    RG log --oneline --no-decorate "$PIN..$new" | head -40 || true

    if checkout "$new" && build && tests && generate; then
        echo "$new" > "$PIN_FILE"
        git -C "$ROOT" commit -q -m "Recompiler pin $(short "$PIN") -> $(short "$new")" \
            -- recomp/RECOMPILER_COMMIT
        echo "OK: pin set to $(short "$new") and committed (not pushed)."
        echo "Next step by hand: boot the game to the title screen and check."
    else
        echo "ERROR with $(short "$new") – back to $(short "$PIN")."
        checkout "$PIN" && build >/dev/null || echo "Rollback failed, please run 'sync'."
        exit 1
    fi
}

case "${1:-}" in
    check)  cmd_check ;;
    sync)   cmd_sync ;;
    test)   tests ;;
    patch)  patches_apply ;;
    update) shift; cmd_update "${1:-}" ;;
    *)      sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
