#!/usr/bin/env bash
# Check interpreter evidence and take it over as functions (recomp/game/ad_floor.discovery.toml).
#   tools/fold.sh [--rom jp|en]
# Sequence: probe generation with the current state → fold_floor_coverage.py over all evidence
# (build/recomp-*/, build/recomp-*/evidence/*/, build/archiv/**) → probe with the new state →
# compare_native_coverage.py. If a previously native instruction is lost, the old
# discovery file is restored (exit 1). Then: tools/build.sh, play, repeat.
# Needs Python with capstone (otherwise automatically via "uv run --with capstone").
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=/dev/null
. "${CONFIG_ENV:-$ROOT/config.env}"
. "$ROOT/tools/rom_select.sh"
variant=""
if [ "${1:-}" = "--rom" ]; then variant=${2:-}; shift 2; fi
rom_select "$variant"
rom_verify

GAME="$ROOT/recomp/game"
DISC="$GAME/ad_floor.discovery.toml"
DENY="$GAME/ad_floor.deny.toml"
PROBE="$ROOT/build/fold-probe"
GR=${GENESIS_RECOMP:-}
[ -n "$GR" ] || for c in "$ROM_BUILD/genesis-recompiler/GenesisRecomp" "$RECOMPILER_DIR/build/recompiler/GenesisRecomp"; do
    [ -x "$c" ] && { GR=$c; break; }; done
[ -x "$GR" ] || { echo "GenesisRecomp not found – run tools/build.sh first"; exit 1; }

if python3 -c 'import capstone' 2>/dev/null; then PY=(python3)
elif command -v uv >/dev/null; then PY=(uv run --quiet --with capstone python3)
else echo "Python module capstone missing (pip install capstone or brew install uv)"; exit 1; fi

generate() {   # $1 = output folder
    rm -rf "$1" && mkdir -p "$1"
    (cd "$GAME" && "$GR" "$ROM_FILE" --game game.toml --output-dir "$1" > "$1/generate.log" 2>&1) ||
        { echo "Generation failed: $1/generate.log"; return 1; }
    grep -E "Final function count|  TOTAL" "$1/generate.log" | sed 's/^ */  /'
}

echo "> Probe before"; generate "$PROBE/before"
cp "$DISC" "$PROBE/discovery.before.toml"

echo "> Checking evidence"
# macOS bash 3.2: no globstar, empty arrays are a problem under set -u → lists via find.
floor=() oracle=()
while IFS= read -r f; do floor+=("$f"); done < <(find "$ROOT/build" -path "$PROBE" -prune -o \
    -type f -name 'floor_coverage*.toml' -print 2>/dev/null | sort)
while IFS= read -r f; do oracle+=("$f"); done < <(find "$ROOT/build" -path "$PROBE" -prune -o \
    -type f -name 'exec_pcs.txt' -size +0 -print 2>/dev/null | sort)
unsafe=()
while IFS= read -r f; do unsafe+=("$f"); done < <(find "$ROOT/build" -path "$PROBE" -prune -o \
    -type f \( -name 'floor_unsafe*.toml' -o -name 'interior_label_misses*.toml' \) -print 2>/dev/null | sort)
[ -f "$DENY" ] && cp "$DENY" "$PROBE/deny.before.toml"
[ ${#floor[@]} -gt 0 ] || { echo "No floor_coverage evidence found"; exit 1; }
echo "  ${#floor[@]} floor_coverage files, ${#oracle[@]} instruction lists, ${#unsafe[@]} unsafe/interior files"
"${PY[@]}" "$ROOT/tools/fold_floor_coverage.py" --rom "$ROM_FILE" --generated "$PROBE/before" \
    --floor "${floor[@]}" --oracle ${oracle[@]+"${oracle[@]}"} --out "$DISC" \
    --unsafe ${unsafe[@]+"${unsafe[@]}"} --deny "$DENY" \
    --keep "$PROBE/discovery.before.toml" > "$PROBE/fold.log"
grep -E "^(denied|removed) \\$" "$PROBE/fold.log" || true
tail -1 "$PROBE/fold.log"

echo "> Probe after"; generate "$PROBE/after"
echo "> Gate"
rc=0
"${PY[@]}" "$ROOT/tools/compare_native_coverage.py" "$PROBE/before" "$PROBE/after" \
    --allow-funcs "$DENY" > "$PROBE/compare.log" || rc=$?
head -1 "$PROBE/compare.log"
if [ "$rc" -eq 0 ]; then
    echo "OK: $DISC updated. Continue with tools/build.sh and playing."
else
    cp "$PROBE/discovery.before.toml" "$DISC"
    if [ -f "$PROBE/deny.before.toml" ]; then cp "$PROBE/deny.before.toml" "$DENY"; else rm -f "$DENY"; fi
    echo "LOSS of native instructions ($PROBE/compare.log) – old discovery file restored."
    exit 1
fi
