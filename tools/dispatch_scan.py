#!/usr/bin/env python3
"""Find code pointers in the ROM that the recompiler has no function for.

    tools/dispatch_scan.py [--generated DIR] [--rom ROM] [--toml]

Every computed jump or call whose target is not a generated function is run by the tier-3
interpreter (docs/notes/recompiler-runs.md). This tool lists such targets *statically*, without
waiting for a play session to hit them:

  menu     handler fields of menu tables (records ID.w, Text.l, Handler.l[, Handler.l], end $FFFF)
           loaded with lea TABLE,a0 – the jmp (a0) / jsr (a0) pattern
  pointer  move.l #ADDR,… / lea ADDR.l,… / pea ADDR.l where ADDR is code – object handlers etc.

Per target: class and the instruction before it.
  entry   follows rts/rte/rtr/bra/jmp – nothing falls into it; a plain undiscovered function
  fall    code falls into it from above – seeding it splits the function there
  STACK   the first instructions take the return address off the stack (movea.l (a7)+,aN or
          addq #4,a7) – must stay in the interpreter (ad_floor.deny.toml), see $011E0A
Targets already denied are marked. --toml prints the entry/fall targets as late_extra lines.
Needs capstone (uv run --with capstone tools/dispatch_scan.py).
"""
import argparse
import bisect
import os
import re
import struct
import sys

import capstone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMINATORS = ("rts", "rte", "rtr", "bra", "jmp")


def in_code(a):   # code areas of the JP ROM (docs/notes/recompiler-runs.md, "Code layout")
    return 0x200 <= a < 0x18000 or 0xFA000 <= a < 0x100000


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generated", default=os.path.join(ROOT, "build/recomp-tr/generated/ad"))
    ap.add_argument("--rom", default=os.path.join(ROOT, "build/rom/ad-tr.md"))
    ap.add_argument("--deny", default=os.path.join(ROOT, "recomp/game/ad_floor.deny.toml"))
    ap.add_argument("--toml", action="store_true")
    args = ap.parse_args()
    rom = open(args.rom, "rb").read()
    decl = open(os.path.join(args.generated, "ad_dispatch.c")).read()
    funcs = sorted(f for f in (int(x, 16) for x in re.findall(r"void func_([0-9A-F]{6})\(void\);", decl))
                   if in_code(f))
    fset = set(funcs)
    denied = set()
    if os.path.exists(args.deny):
        denied = {int(x, 16) for x in re.findall(r"^\s*0x([0-9A-Fa-f]+)", open(args.deny).read(), re.M)}
    u16 = lambda a: struct.unpack_from(">H", rom, a)[0]
    u32 = lambda a: struct.unpack_from(">I", rom, a)[0]

    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    insns, prev = {}, {}
    for k, f in enumerate(funcs):   # linear decode per function, up to the next function
        end = funcs[k + 1] if k + 1 < len(funcs) else f + 0x100
        last = None
        for i in md.disasm(rom[f:min(end, f + 0x4000)], f):
            insns[i.address] = i
            if last is not None:
                prev[i.address] = last
            last = i

    def owner(v):
        return funcs[bisect.bisect_right(funcs, v) - 1]

    def is_code(v):
        return v % 2 == 0 and in_code(v) and v in insns

    found = {}   # target -> [(kind, where)]
    for a, i in sorted(insns.items()):
        op, val = u16(a), None
        if i.mnemonic == "move.l" and (op & 0x3F) == 0x3C and i.size >= 6 and (op >> 6) & 7 != 0:
            val = u32(a + 2)            # move.l #imm to memory (not to a data register)
        elif i.mnemonic in ("lea.l", "pea.l") and (op & 0x3F) == 0x39:
            val = None                  # lea abs.l is nearly always data (tables); tables: below
        if val is not None and is_code(val) and val not in fset:
            found.setdefault(val, []).append(("pointer", f"${a:06X} {i.mnemonic} {i.op_str}"))
        if not i.mnemonic.startswith("lea"):
            continue
        if (op & 0x3F) == 0x3A:
            t = a + 2 + struct.unpack_from(">h", rom, a + 2)[0]
        elif (op & 0x3F) == 0x39:
            t = u32(a + 2)
        else:
            continue
        if not in_code(t):
            continue
        for stride, offs in ((10, (6,)), (14, (6, 10))):
            recs, p = [], t
            while len(recs) < 40 and u16(p) != 0xFFFF and all(is_code(u32(p + o)) for o in offs):
                recs.append([u32(p + o) for o in offs])
                p += stride
            if len(recs) >= 2 and u16(p) == 0xFFFF:
                for r in recs:
                    for h in r:
                        if h not in fset:
                            found.setdefault(h, []).append(("menu", f"table ${t:06X} (lea at ${a:06X})"))
                break

    seeds = []
    for v in sorted(found):
        p = prev.get(v)
        cls = "entry" if p is not None and p.mnemonic.split(".")[0] in TERMINATORS else "fall"
        head, x = [], v
        while x in insns and len(head) < 6:
            head.append(insns[x])
            if insns[x].mnemonic.split(".")[0] in TERMINATORS:
                break
            x += insns[x].size
        text = "; ".join(f"{i.mnemonic} {i.op_str}".strip() for i in head)
        if re.search(r"movea\.l \(a7\)\+, a\d|addq\.[wl] #\$?4, a7", text):
            cls = "STACK"
        note = " [denied]" if v in denied or owner(v) in denied else ""
        refs = sorted({k for k, _ in found[v]})
        if args.toml:
            if cls != "STACK" and not note:
                seeds.append(f"  0x{v:06X},  # {'/'.join(refs)}, {cls}: {found[v][0][1]}")
            continue
        print(f"${v:06X} {cls:5s} {'/'.join(refs):12s} in ${owner(v):06X}{note}")
        print(f"         before: {p.mnemonic + ' ' + p.op_str if p is not None else '?'}")
        print(f"         code:   {text}")
        for _, where in found[v][:4]:
            print(f"         from:   {where}")
    if args.toml:
        print("\n".join(seeds))
    else:
        print(f"{len(found)} targets without a function", file=sys.stderr)


if __name__ == "__main__":
    main()
