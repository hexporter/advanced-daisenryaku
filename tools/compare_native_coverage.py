#!/usr/bin/env python3
"""Gate after regenerating: every instruction emitted natively before must still be
emitted natively afterwards. A new function start can cut off an existing function;
the rest would then silently run in the interpreter. Exit 1 on loss.

After RocketKnightAdventuresRecomp/tools/compare_native_coverage.py (mstan, PolyForm NC 1.0.0).
Usage: compare_native_coverage.py <generated-before> <generated-after> [--allow-funcs FILE]
--allow-funcs: deny list (0x… entries); instructions inside these functions (range according
to <before>) may be lost – an intentional fallback to the interpreter.
"""
import glob
import re
import sys
from pathlib import Path

args = sys.argv[1:]
allow_file = None
if '--allow-funcs' in args:
    i = args.index('--allow-funcs'); allow_file = args[i + 1]; del args[i:i + 2]
if len(args) != 2:
    sys.exit(__doc__)


def emitted(d):
    out = set()
    for f in glob.glob(str(Path(d) / '*_part*.c')):
        out.update(int(m, 16) for m in re.findall(r'/\* \$([0-9A-F]{6}) \*/', open(f).read()))
    return out


def funcs(d):
    out = set()
    for f in glob.glob(str(Path(d) / '*_part*.c')):
        out.update(re.findall(r'^void func_([0-9A-F]{6})\(void\)', open(f).read(), re.M))
    return len(out)


def spans(d):
    out = {}
    for f in glob.glob(str(Path(d) / '*_part*.c')):
        for body in re.split(r'^void func_', open(f).read(), flags=re.M)[1:]:
            pcs = [int(m, 16) for m in re.findall(r'/\* \$([0-9A-F]{6}) \*/', body)]
            if pcs:
                out[int(body[:6], 16)] = (min(pcs), max(pcs))
    return out


before, after = emitted(args[0]), emitted(args[1])
allowed = set()
if allow_file and Path(allow_file).exists():
    sp = spans(args[0])
    for m in re.findall(r'^\s*0x([0-9A-Fa-f]{6})', open(allow_file).read(), re.M):
        lo_hi = sp.get(int(m, 16))
        if lo_hi:
            allowed.update(pc for pc in before if lo_hi[0] <= pc <= lo_hi[1])
lost = sorted(before - after - allowed)
print(f'Functions before {funcs(args[0])} after {funcs(args[1])}; '
      f'instructions before {len(before)} after {len(after)} gained {len(after - before)} '
      f'lost {len(lost)} (intentionally to the interpreter: {len((before - after) & allowed)})')
for pc in lost[:200]:
    print(f'lost ${pc:06X}')
sys.exit(1 if lost else 0)
