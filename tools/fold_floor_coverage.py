#!/usr/bin/env python3
"""Take over interpreter evidence (tier-3 floor) into a discovery file, after validation.

Modelled on RocketKnightAdventuresRecomp/tools/fold_floor_coverage.py
(mstan, PolyForm Noncommercial 1.0.0), adapted for this project.

Inputs: floor_coverage*.toml (targets the interpreter executed as call/jump targets)
and optionally exec_pcs.txt (instruction starts executed by the interpreter, --exec-coverage-out).

A target is taken over if
  * it lies in the ROM, is even and is not a generated function yet,
  * it does NOT lie inside an existing function (otherwise the recompiler would cut off the
    parent function – interior labels are never seeds),
  * its straight run up to the first control transfer decodes cleanly and
  * (with an instruction list) every instruction of that run was actually executed.
Without an instruction list for a target only the static check applies; such entries are
marked "static" in the output.

Taken-over targets become [functions].late_extra (not recursive: no new heuristic growth).

Deny list (--deny): addresses that never become functions (also a recompiler blacklist).
Extended automatically: if an unsafe interpreter jump (floor_unsafe*.toml) or an interior-label
miss lies in a function an earlier fold took over, the WHOLE subtree from its floor root
(floor_entry in the evidence) is denied – stack tricks like skip returns can only be handled by
the interpreter across the whole chain (example: yes/no dialog $011DC6 in subtree $0117AA,
handler $011E0A does movea.l (a7)+,a0 / rts).
Always check for losses with tools/compare_native_coverage.py afterwards (tools/fold.sh does both).
"""
import argparse
import glob
import re
from pathlib import Path

import capstone

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--rom', type=Path, required=True)
p.add_argument('--generated', type=Path, required=True, help='folder with ad_part*.c')
p.add_argument('--floor', nargs='+', required=True, help='floor_coverage*.toml (globs allowed)')
p.add_argument('--oracle', nargs='*', default=[], help='exec_pcs.txt (globs allowed)')
p.add_argument('--out', type=Path, required=True)
p.add_argument('--keep', type=Path, help='existing discovery file whose entries are kept')
p.add_argument('--unsafe', nargs='*', default=[], help='floor_unsafe*/interior_label_misses*.toml (globs)')
p.add_argument('--deny', type=Path, help='deny list (read and extended)')
a = p.parse_args()

rom = a.rom.read_bytes()
md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_M68K_000)

STATIC, ORACLE = 'static', 'instruction list'
# Comments written before the switch to English (31.10.2026).
LEGACY = {'statisch': STATIC, 'Befehlsliste': ORACLE, 'behalten': 'kept'}


def files(patterns):
    out = []
    for pat in patterns:
        out += sorted(glob.glob(pat, recursive=True))
    return sorted(set(out))


gen, starts, spans = set(), set(), []
for f in sorted(a.generated.glob('*_part*.c')):
    text = f.read_text()
    gen.update(int(m, 16) for m in re.findall(r'/\* \$([0-9A-F]{6}) \*/', text))
    starts.update(int(m, 16) for m in re.findall(r'^void func_([0-9A-F]{6})\(void\)', text, re.M))
    # The recompiler ends a function at the next function start: a seed in a gap of its
    # address range cuts it off as well.
    for body in re.split(r'^void func_', text, flags=re.M)[1:]:
        pcs = [int(m, 16) for m in re.findall(r'/\* \$([0-9A-F]{6}) \*/', body)]
        if pcs:
            spans.append((int(body[:6], 16), max(pcs)))
if not gen or not starts:
    p.error('--generated contains no generated functions (*_part*.c)')


def interior(addr):
    return addr in gen or any(lo < addr <= hi for lo, hi in spans)


oracle_files = files(a.oracle)
oracle = set()
for f in oracle_files:
    for line in open(f):
        line = line.strip()
        if line and not line.startswith('#'):
            oracle.add(int(line, 16))

floor_files = files(a.floor)
floor = set()
root_of = {}      # address -> floor root (its own address if it is a root itself)
for f in floor_files:
    for m in re.finditer(r'^\s*0x([0-9A-Fa-f]{6}),[^\n]*', open(f).read(), re.M):
        x = int(m.group(1), 16)
        floor.add(x)
        r = re.search(r'floor_entry \$([0-9A-Fa-f]{6})', m.group(0))
        root_of.setdefault(x, set()).add(int(r.group(1), 16) if r else x)

TRANSFER = ('rts', 'rte', 'rtr', 'jmp', 'jsr', 'bra', 'bsr', 'dbra', 'trap')


def is_transfer(mnemonic):
    m = mnemonic.split('.')[0]
    if m in ('sub', 'subq', 'subi', 'suba', 'subx', 'swap', 'bset', 'bclr', 'bchg', 'btst'):
        return False
    return m in TRANSFER or m.startswith(('b', 'db', 's'))


def validate(entry, use_oracle):
    """Straight run up to the first transfer: everything decoded; with an instruction list also
    everything executed (the floor capsule only "peeks" at the final RTS)."""
    pc = entry
    for _ in range(64):
        if pc + 2 > len(rom):
            return f'${pc:06X} beyond the end of the ROM'
        ins = next(md.disasm(rom[pc:pc + 10], pc, 1), None)
        if ins is None or ins.mnemonic.startswith('.'):
            return f'${pc:06X} not decodable'
        if is_transfer(ins.mnemonic):
            if use_oracle and pc == entry and not ins.mnemonic.startswith(('rts', 'rtr')) and pc not in oracle:
                return f'${pc:06X} not executed'
            return None
        if use_oracle and pc not in oracle:
            return f'${pc:06X} not executed'
        pc += ins.size
    return None


kept = {}
if a.keep and a.keep.exists():
    for m in re.finditer(r'^\s*0x([0-9A-Fa-f]{6}),\s*(#.*)?$', a.keep.read_text(), re.M):
        note = (m.group(2) or '# kept').lstrip('# ').strip()
        kept[int(m.group(1), 16)] = LEGACY.get(note, note)

deny = {}
if a.deny and a.deny.exists():
    for m in re.finditer(r'^\s*0x([0-9A-Fa-f]{6}),\s*(#.*)?$', a.deny.read_text(), re.M):
        deny[int(m.group(1), 16)] = (m.group(2) or '').lstrip('# ').strip()

import bisect
start_list = sorted(starts)


def region_end(x):
    """Next generated function start after x – a function at x would have reached that far."""
    i = bisect.bisect_right(start_list, x)
    return start_list[i] if i < len(start_list) else len(rom)


def in_denied_region(x):
    """x lies in the range of a denied function (like interior labels: never a seed)."""
    return any(d <= x < region_end(d) for d in deny)


# Drop entries already taken over that lie in denied ranges (e.g. handler $011E0A).
dropped = [k for k in kept if k not in deny and in_denied_region(k)]
for d in dropped:
    kept.pop(d, None)

# Unsafe jumps in functions an earlier fold took over → deny the connected subtree: fold entries
# with the same floor root in the address range root … end of the affected function (under one
# root the interpreter also logs everything it calls, hence no denial beyond that range).
unsafe_files = files(a.unsafe)
unsafe = set()
for f in unsafe_files:
    unsafe.update(int(m, 16) for m in re.findall(r'^\s*0x([0-9A-Fa-f]{6})', open(f).read(), re.M))
newly_denied = []
for u in sorted(unsafe):
    owners = [lo for lo, hi in spans if lo <= u <= hi and lo in kept]
    for lo in owners:
        roots = root_of.get(lo, {lo})
        lo_bound, hi_bound = min(roots | {lo}), region_end(lo)
        subtree = {x for x in kept if root_of.get(x, set()) & roots and lo_bound <= x < hi_bound}
        subtree |= {r for r in roots if r in kept} | {lo}
        for x in sorted(subtree):
            if x not in deny:
                deny[x] = (f'subtree ${min(roots):06X}: unsafe jump/interior label ${u:06X} '
                           f'in ${lo:06X} (from evidence)')
                newly_denied.append(x)
for d in deny:
    kept.pop(d, None)

accepted, rejected = dict(kept), []
for addr in sorted(floor - set(kept)):
    if addr >= len(rom) or addr & 1 or (addr in starts and addr not in deny):
        continue
    if addr in deny or in_denied_region(addr):
        rejected.append((addr, 'lies in the range of a denied function'))
        continue
    if interior(addr):
        rejected.append((addr, 'lies in an existing function (interior label, never a seed)'))
        continue
    use_oracle = addr in oracle
    why = validate(addr, use_oracle)
    if why:
        rejected.append((addr, why))
    else:
        accepted[addr] = ORACLE if use_oracle else STATIC

n_static = sum(1 for v in accepted.values() if v == STATIC)
lines = [
    '# Validated interpreter targets (tools/fold_floor_coverage.py). Do not edit by hand;',
    '# regenerate with tools/fold.sh. Comment per entry: kind of validation.',
    f'# Evidence: {len(floor_files)} floor_coverage files, {len(oracle_files)} instruction lists',
    f'# taken over={len(accepted)} (of which checked statically={n_static}) rejected={len(rejected)}',
    '',
    '[functions]',
    'late_extra = [',
]
lines += [f'  0x{x:06X},  # {accepted[x]}' for x in sorted(accepted)]
lines.append(']')
a.out.write_text('\n'.join(lines) + '\n')
if a.deny:
    dl = ['# Deny list (tools/fold.sh): these addresses never become functions – neither via fold nor',
          '# via heuristics (recompiler blacklist via discovery_files); they run in the interpreter.',
          '# Extended automatically from floor_unsafe/interior_label_misses; entries may be added',
          '# by hand (with the reason as a comment).', '', '[functions]', 'blacklist = [']
    dl += [f'  0x{x:06X},  # {deny[x]}' for x in sorted(deny)]
    dl.append(']')
    a.deny.write_text('\n'.join(dl) + '\n')
for x in newly_denied:
    print(f'denied ${x:06X}: {deny[x]}')
for x in sorted(dropped):
    print(f'removed ${x:06X}: lies in the range of a denied function')
for addr, why in rejected:
    print(f'rejected ${addr:06X}: {why}')
print(f'newly denied {len(newly_denied)}; taken over {len(accepted)} (new {len(accepted) - len(kept)}, static {n_static}), '
      f'rejected {len(rejected)} ({sum("interior" in w for _, w in rejected)} interior) -> {a.out}')
