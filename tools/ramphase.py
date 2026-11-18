#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["numpy"]
# ///
"""Analyse RAM recordings (tools/run.sh --ramlog) by phase.

Looks for RAM bytes and bits whose values separate the marked phases
(0 other, 1 own turn, 2 enemy turn, 3 battle), see docs/notes/phases.md.

  tools/ramphase.py LOG [LOG …]                       candidates: enemy turn against own turn + battle
  tools/ramphase.py LOG --target 3 --against 1 2      battle against the rest
  tools/ramphase.py LOG --show FF0110 FFCDA0          history of these addresses with the phase
  tools/ramphase.py LOG --phases                      phase changes and durations

Records shortly after a phase change (--margin, default 60 V-ints) don't count,
because the marking by hand lags behind.
"""
import argparse
import struct
import sys

import numpy as np

NAMES = {0: "other", 1: "own turn", 2: "enemy turn", 3: "battle"}


def read(path):
    """Returns a list of (vint, phase, ram) – ram as np.uint8[65536], reconstructed per record."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"ADRAMLG1":
        sys.exit(f"{path}: not a RAM recording")
    pos, ram, out = 8, np.zeros(0x10000, np.uint8), []
    while pos + 12 <= len(data):
        vint, phase, kind, _, n = struct.unpack_from(">IBBHI", data, pos)
        pos += 12
        if kind == 0:
            if pos + 0x10000 > len(data):
                break
            ram = np.frombuffer(data, np.uint8, 0x10000, pos).copy()
            pos += 0x10000
        else:
            if pos + 3 * n > len(data):
                break          # truncated end (crash, Ctrl+C)
            e = np.frombuffer(data, np.uint8, 3 * n, pos).reshape(n, 3)
            pos += 3 * n
            ram = ram.copy()
            ram[(e[:, 0].astype(np.uint32) << 8) | e[:, 1]] = e[:, 2]
        out.append((vint, phase, ram))
    return out


def without_margin(records, margin):
    """Records without the first `margin` V-ints after each phase change."""
    last_phase, changed, out = None, 0, []
    for vint, phase, ram in records:
        if phase != last_phase:
            last_phase, changed = phase, vint
        if vint - changed >= margin:
            out.append((vint, phase, ram))
    return out


def candidates(records, target, against, count):
    """Bytes/bits whose value sets in `target` and `against` are disjoint,
    then the best fuzzy separators (boundary noise, several recordings)."""
    freq = {p: np.zeros((0x10000, 256), np.uint32) for p in [target] + against}
    total = {p: 0 for p in freq}
    idx = np.arange(0x10000)
    for _, phase, ram in records:
        if phase in freq:
            freq[phase][idx, ram] += 1
            total[phase] += 1
    for p in freq:
        print(f"Phase {p} ({NAMES.get(p, '?')}): {total[p]} records")
    if not total[target] or not all(total[p] for p in against):
        sys.exit("Not enough data: every compared phase needs records.")

    tc = freq[target]
    rc = sum(freq[p] for p in against)
    t, r = tc > 0, rc > 0
    separates = ~(t & r).any(axis=1)
    # Addresses without any change across all phases are uninteresting (cannot be disjoint anyway).
    width = t.sum(axis=1) + r.sum(axis=1)
    hits = sorted(np.nonzero(separates)[0], key=lambda a: (width[a], a))
    print(f"\nBytes separating phase {target} from {against}: {len(hits)}")
    for a in hits[:count]:
        tv = " ".join(f"{v:02X}" for v in np.nonzero(t[a])[0][:12])
        rv = " ".join(f"{v:02X}" for v in np.nonzero(r[a])[0][:12])
        print(f"  $FF{a:04X}  target: {tv:<36}  rest: {rv}")

    # Bits: constant within the target phase, constant in the rest, and different.
    values = np.arange(256)
    bit_hits = []
    for b in range(8):
        mask = ((values >> b) & 1).astype(bool)
        t1, t0 = (t & mask).any(axis=1), (t & ~mask).any(axis=1)
        r1, r0 = (r & mask).any(axis=1), (r & ~mask).any(axis=1)
        for a in np.nonzero((t1 ^ t0) & (r1 ^ r0) & (t1 != r1))[0]:
            if not separates[a] or width[a] > 2:
                bit_hits.append((a, b, int(t1[a])))
    print(f"\nSingle bits (in addition to the bytes above): {len(bit_hits)}")
    for a, b, v in sorted(bit_hits)[:count]:
        print(f"  $FF{a:04X} bit {b}: target {v}, rest {1 - v}")
    fuzzy(tc / tc.sum(axis=1, keepdims=True), rc / rc.sum(axis=1, keepdims=True), count)


def fuzzy(pt, pr, count):
    """Balanced hit rate of the best value or bit assignment per address:
    0.5 · Σ max(P(value|target), P(value|rest)); 50 % = does not separate, 100 % = perfect."""
    rate = 0.5 * np.maximum(pt, pr).sum(axis=1)
    print(f"\nBest fuzzy separators (bytes):")
    for a in np.argsort(-rate, kind="stable")[:count]:
        def dist(p):
            top = np.argsort(-p[a])[:5]
            return " ".join(f"{v:02X}:{p[a, v]:.0%}" for v in top if p[a, v] >= 0.005)
        print(f"  $FF{a:04X} {rate[a]:6.1%}  target {dist(pt):<40} rest {dist(pr)}")
    values = np.arange(256)
    bits = []
    for b in range(8):
        mask = ((values >> b) & 1).astype(bool)
        t1, r1 = pt[:, mask].sum(axis=1), pr[:, mask].sum(axis=1)
        q = 0.5 * (1 + np.abs(t1 - r1))
        for a in np.argsort(-q, kind="stable")[:count]:
            bits.append((q[a], a, b, t1[a], r1[a]))
    print(f"\nBest fuzzy separators (bits):")
    for q, a, b, t1, r1 in sorted(bits, key=lambda x: -x[0])[:count]:
        print(f"  $FF{a:04X} bit {b} {q:6.1%}  set: target {t1:.0%}, rest {r1:.0%}")


def show(records, addresses):
    for a in addresses:
        a &= 0xFFFF
        print(f"\n$FF{a:04X}: V-int  phase  value")
        last = None
        for vint, phase, ram in records:
            key = (phase, ram[a])
            if key != last:
                print(f"  {vint:8d}  {phase} {NAMES.get(phase, '?'):<12} {ram[a]:02X}")
                last = key


def phases(records):
    last, start = None, 0
    for vint, phase, _ in records + [(records[-1][0], None, None)]:
        if phase != last:
            if last is not None:
                print(f"  V-int {start:8d}–{vint:8d}  ({(vint - start) / 60:6.1f} s)  {last} {NAMES.get(last, '?')}")
            last, start = phase, vint


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--target", type=int, default=2)
    ap.add_argument("--against", type=int, nargs="+", default=[1, 3])
    ap.add_argument("--margin", type=int, default=60, help="V-ints to ignore after a phase change")
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--show", nargs="+", type=lambda s: int(s.lstrip("$"), 16))
    ap.add_argument("--phases", action="store_true")
    a = ap.parse_args()

    records, trimmed = [], []
    for path in a.logs:
        r = read(path)
        print(f"{path}: {len(r)} records")
        records += r
        trimmed += without_margin(r, a.margin)
    if not records:
        sys.exit("No records.")
    if a.phases:
        phases(records)
    elif a.show:
        show(records, a.show)
    else:
        candidates(trimmed, a.target, a.against, a.count)


if __name__ == "__main__":
    main()
