#!/usr/bin/env python3
"""Convert save games between the port and emulators (docs/notes/saving.md).

The game's SRAM sits on the odd bytes of $200001–$20FFFF (32 KiB of data). The port writes the whole
64 KiB address range raw (`build/recomp-<variant>/<ROM name>.srm`, even bytes 0). Emulators store
either the 32 KiB of odd bytes alone or the 64 KiB range. Genesis Plus GX fills the range with $FF
(even bytes stay $FF) and cuts trailing $FF bytes off the file, so it can be shorter than 64 KiB.

    srm_convert.py to-emu PORT.srm OUT.srm [--full]   32 KiB odd bytes (--full: 64 KiB like the port)
    srm_convert.py to-port EMU.srm OUT.srm            32 KiB, or up to 64 KiB (trimmed) in, 64 KiB port layout out
    srm_convert.py names IN.srm OUT.srm --from ROM --to ROM
                                                      replace 8-character names the game copied into the
                                                      save from one ROM (e.g. the EN patch: "Germany") by
                                                      the other ROM's names at the same table index
                                                      (e.g. build/rom/ad-tr.md: "Dt.Reich"); layout kept

The tool warns when the file holds no data at all. Back up the target first: OUT is overwritten.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adtext import TEXT_TABLES, load_charmap  # noqa: E402

SIZE = 0x10000
DATA = SIZE // 2


def unused(lane):
    return all(b == 0 for b in lane) or all(b == 0xFF for b in lane)


def odd_bytes(raw):
    """The 32 KiB of game data from a 32 KiB file or a (possibly trimmed) 64 KiB file."""
    if len(raw) == DATA:
        return raw
    if len(raw) > SIZE:
        sys.exit(f"unexpected size {len(raw)} (expected {DATA} or up to {SIZE} bytes)")
    if len(raw) < SIZE:
        print(f"note: {len(raw)} bytes, padding with $FF to {SIZE} (trimmed emulator file)", file=sys.stderr)
        raw = raw + b"\xff" * (SIZE - len(raw))
    odd, even = raw[1::2], raw[0::2]
    if unused(even):
        return odd
    if unused(odd):
        return even          # data on the even offsets (byte-swapped writer)
    sys.exit("both byte lanes contain data – not an odd-byte SRAM file")


def put_back(raw, data):
    """The file raw with its SRAM data replaced, same size and byte lane as odd_bytes() read it."""
    if len(raw) == DATA:
        return data
    full = bytearray(raw + b"\xff" * (SIZE - len(raw)))
    lane = 0 if unused(full[1::2]) and not unused(full[0::2]) else 1
    full[lane::2] = data
    return bytes(full[:len(raw)])


def decode(record, chars):
    return "".join(" " if c == 0x14 else chars.get(c, "?") for c in record)


def check(data):
    if unused(data):
        print("warning: the SRAM holds no data (all $00 or all $FF)", file=sys.stderr)


def name_map(src, dst):
    """8-character name records that differ between two ROMs: {src record: dst record}.
    Tables of docs/notes/text-map.md; a record that maps to two different names is left out."""
    names, clash = {}, set()
    for section, base, count, stride, fmt in TEXT_TABLES:
        if fmt == "len" and section != "armies":       # 16x16 lists, the PAX GERMANA line
            continue
        first = base + (1 if fmt == "len" else 0)
        for i in range(count):
            a = first + i * stride
            old, new = bytes(src[a:a + 8]), bytes(dst[a:a + 8])
            if old != new:
                if names.get(old, new) != new:
                    clash.add(old)
                names[old] = new
    for old in clash:
        del names[old]
    return names


# Save slots (load routine $0119AA, docs/notes/saving.md): six blocks copied to RAM back to back,
# then at +$2A00 the signature (compared by $011BE8 with $011C1A) and one big-endian long per block,
# the 32-bit sum of its bytes. Offsets in the 32 KiB of data.
SIGNATURE = b"SEGA MEGA DRIVE (C)SEGA 1990.AUGSUPER DAISENRYAK      BACKUP RAM"
BLOCKS = (0x100, 0x1000, 0x1400, 0x200, 0x200, 0x100)   # $FFCC00, $FFA000, $FFB000, $FFC800, $FF4000, $FFCA00
SUMS = 0x2A00 + len(SIGNATURE)


def slots(data):
    """Start offsets of the slots with a signature."""
    out, i = [], data.find(SIGNATURE)
    while i >= 0:
        out.append(i - 0x2A00)
        i = data.find(SIGNATURE, i + 1)
    return [b for b in out if b >= 0]


def block_sums(data, base):
    sums, pos = [], base
    for n in BLOCKS:
        sums.append(sum(data[pos:pos + n]) & 0xFFFFFFFF)
        pos += n
    return sums


def stored_sums(data, base):
    return [int.from_bytes(data[base + SUMS + 4 * i:base + SUMS + 4 * i + 4], "big") for i in range(len(BLOCKS))]


def rename(data, names):
    """Replace every name record in the SRAM data; returns the new data and the count per name."""
    data = bytearray(data)
    counts = {}
    for old, new in names.items():
        i = data.find(old)
        while i >= 0:
            data[i:i + 8] = new
            counts[old] = counts.get(old, 0) + 1
            i = data.find(old, i + 8)
    return bytes(data), counts


def fix_sums(old, new):
    """Recompute the sums of every slot that was intact in old; returns the slots fixed."""
    new = bytearray(new)
    fixed = []
    for base in slots(old):
        if stored_sums(old, base) != block_sums(old, base):
            print(f"note: slot at ${base:04X} was already corrupt, sums left as they are", file=sys.stderr)
            continue
        sums = block_sums(new, base)
        if sums != stored_sums(new, base):
            new[base + SUMS:base + SUMS + 4 * len(sums)] = b"".join(x.to_bytes(4, "big") for x in sums)
            fixed.append(base)
    return bytes(new), fixed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("direction", choices=("to-emu", "to-port", "names"))
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--full", action="store_true", help="to-emu: write 64 KiB (even bytes $FF, like Genesis Plus GX)")
    ap.add_argument("--from", dest="src", help="names: ROM whose names the save holds")
    ap.add_argument("--to", dest="dst", help="names: ROM whose names it should hold")
    args = ap.parse_args()
    raw = open(args.inp, "rb").read()
    data = odd_bytes(raw)
    check(data)
    if args.direction == "names":
        if not (args.src and args.dst):
            sys.exit("names needs --from ROM and --to ROM")
        chars = load_charmap()
        names = name_map(open(args.src, "rb").read(), open(args.dst, "rb").read())
        renamed, counts = rename(data, names)
        data, fixed = fix_sums(data, renamed)
        for old, n in sorted(counts.items(), key=lambda i: -i[1]):
            print(f"{n:3}x {decode(old, chars).rstrip()!r} -> {decode(names[old], chars).rstrip()!r}")
        if not counts:
            print("no names of --from found in the save")
        if fixed:
            print("checksums recomputed for the slots at " + ", ".join(f"${b:04X}" for b in fixed))
        with open(args.out, "wb") as f:
            f.write(put_back(raw, data))
        print(f"{args.out}: {len(raw)} bytes, same layout as {args.inp}")
        return
    if args.direction == "to-emu" and not args.full:
        out = data
    else:
        out = bytearray(b"\xff" * SIZE if args.direction == "to-emu" else SIZE)   # even bytes: emulator $FF, port 0
        out[1::2] = data
    with open(args.out, "wb") as f:
        f.write(out)
    print(f"{args.out}: {len(out)} bytes")


if __name__ == "__main__":
    main()
