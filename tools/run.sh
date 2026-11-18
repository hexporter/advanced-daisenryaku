#!/usr/bin/env bash
# Start the built game.
#   tools/run.sh [--rom jp|en|tr] [--ramlog] [--no-hd] [--no-wide] [RUNNER ARGUMENTS …]   e.g. tools/run.sh --rom en --max-frames 600
# --ramlog: RAM recording with phase marking to evidence/<time>/ramlog.bin (docs/notes/phases.md)
# HD graphics: build/hd/pack.bin (tools/hdpack.py build) is loaded when present; --no-hd skips it.
# In the game F10 switches between HD and the original graphics (docs/notes/hd-graphics.md).
# 16:9: with the HD frame the picture gets side margins of 39 screen pixels (GENESIS_HD_MARGIN,
# framework patch 0010); the zoomed-out map (F9) fills them, other screens leave them black.
# --no-wide: the 320x224 frame as before (docs/notes/map.md).
# Without --rom, ROM_VARIANT from config.env applies (default jp).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=/dev/null
. "${CONFIG_ENV:-$ROOT/config.env}"
. "$ROOT/tools/rom_select.sh"

variant=""
ramlog=0
hd=1
wide=1
while [ $# -gt 0 ]; do
    case "$1" in
        --rom)    variant=${2:-}; shift 2 ;;
        --ramlog) ramlog=1; shift ;;
        --no-hd)  hd=0; shift ;;
        --no-wide) wide=0; shift ;;
        *) break ;;
    esac
done
rom_select "$variant"
BIN="$ROM_BUILD/ADRecomp$EXE"
[ -x "$BIN" ] || { echo "Not built: tools/build.sh --rom $ROM_VARIANT"; exit 1; }

# The runner stores miss logs and save games next to the binary, separately per variant.
# Console output additionally goes to run.log (previous run: run.prev.log).
# Evidence per session: evidence/<time>/ with exec_pcs.txt (instructions executed by the interpreter,
# --exec-coverage-out, only on normal exit) and copies of the *.toml logs.
# Analysis: tools/fold_floor_coverage.py
cd "$ROM_BUILD"
[ -f run.log ] && mv -f run.log run.prev.log
session="evidence/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$session"
[ "$ramlog" = 1 ] && export AD_RAMLOG="$ROM_BUILD/$session/ramlog.bin"
HD_PACK="$ROOT/build/hd/pack.bin"
if [ "$hd" = 1 ] && [ -f "$HD_PACK" ] && [ -z "${GENESIS_HD_PACK:-}" ]; then export GENESIS_HD_PACK="$HD_PACK"; fi
if [ "$wide" = 1 ] && [ -n "${GENESIS_HD_PACK:-}" ] && [ -z "${GENESIS_HD_MARGIN:-}" ]; then export GENESIS_HD_MARGIN=39; fi
set +e
"$BIN" --exec-coverage-out "$session/exec_pcs.txt" "$@" "$ROM_FILE" 2>&1 | tee run.log
rc=${PIPESTATUS[0]}
[ "$rc" -ne 0 ] && echo "Runner exited with code $rc (signal $((rc > 128 ? rc - 128 : 0)))" | tee -a run.log
cp -f ./*.toml run.log "$session"/ 2>/dev/null
exit "$rc"
