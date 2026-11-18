#!/usr/bin/env python3
"""Text encoding of Advanced Daisenryaku (docs/notes/text.md).

Strings: length byte (glyph count - 1), then one code per glyph. A code byte < $FD is the glyph
index; $FD/$FE/$FF xx is index $FD + ($00/$100/$200) + xx. Glyphs are 16x16, 1 bpp, 32 bytes
(8x8 blocks top-left, top-right, bottom-left, bottom-right) at FONT_BASE + index * 32.
The character map is translation/charmap.txt; the 8x8 font at $03850E uses the same codes
$00-$A7 (no kanji). Text areas: docs/notes/text-map.md.

    tools/adtext.py dump ROM ADDR [ADDR ...] [--lines N]   decode N consecutive strings per address
    tools/adtext.py intro ROM                              decode the intro captions
    tools/adtext.py catalog ROM [--out FILE]               all known text as TSV (default stdout)
    tools/adtext.py briefings ROM                          decode the packed briefing blocks

Briefings (docs/notes/briefings.md) are LZSS-packed blocks of rows: control byte, then codes.
Control bit 7 = blank row (no codes), bit 6 = last row of the entry, bits 0-5 = glyph count - 1.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARMAP = os.path.join(ROOT, "translation", "charmap.txt")
FONT_BASE = 0x03C86A
FONT_GLYPHS = 0x35E

# Intro captions (docs/notes/text.md): call site of "lea <string>,a0", original string address,
# number of lines read one after the other from that address.
INTRO_CAPTIONS = [
    (0x000EF2, 0x0EFB7D, 1),
    (0x000FBE, 0x0EFB92, 1),
    (0x000FE0, 0x0EFBA3, 1),
    (0x00109A, 0x0EFBB7, 2),
    (0x001170, 0x0EFBDD, 2),
    (0x00128C, 0x0EFC09, 2),
    (0x0013AC, 0x0EFC2F, 1),
    (0x0014B8, 0x0EFC46, 2),
]

# Text areas (docs/notes/text-map.md). Tables: (section, first record, count, stride, format);
# format "len" = length-prefixed string, "fixN" = N characters without length byte.
TEXT_BLOCK = (0x0EF107, 0x0F0000)   # strings found through pointers into the block, see catalog()
TEXT_TABLES = [
    ("armies", 0x0233F0, 82, 9, "len"),
    ("misc", 0x0236D2, 1, 0, "len"),
    ("movement", 0x02376A, 23, 4, "len"),
    ("classes", 0x0237C6, 44, 7, "len"),
    ("terrain", 0x02AE76, 99, 8, "fix8"),
    ("units", 0x02B1F2, 690, 34, "fix8"),
    ("weapons", 0x033DB6, 159, 8, "fix8"),
    ("scenarios", 0x07EEB8, 45, 0x70, "fix8"),
]

# Packed briefing blocks (docs/notes/briefings.md): (name, packed data, offset table, table
# entries). The game unpacks a block to $FF2000 and draws entry k from $FF2000 + table[k].
BRIEFINGS = [
    ("missions", 0x023EB6, 0x023E5E, 44),
    ("results", 0x02539A, 0x0252DE, 94),
]


def load_charmap(path=CHARMAP):
    chars = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            start, text = line.split(" ", 1)
            for i, c in enumerate(text):
                chars[int(start, 16) + i] = c
    if len(chars) != FONT_GLYPHS:
        sys.exit(f"charmap: {len(chars)} glyphs, expected {FONT_GLYPHS}")
    return chars


def read_codes(rom, addr):
    """Glyph indices of the string at addr and the address after it."""
    count = rom[addr] + 1
    pos = addr + 1
    codes = []
    for _ in range(count):
        b = rom[pos]
        pos += 1
        if b >= 0xFD:
            b = ((b - 0xFD) << 8) + rom[pos] + 0xFD
            pos += 1
        codes.append(b)
    return codes, pos


def decode(codes, chars):
    return "".join(chars.get(c, f"{{{c:03X}}}") for c in codes)


def glyph_bits(rom, index):
    """16 rows of 16 pixels (lists of 0/1) of a font glyph."""
    d = rom[FONT_BASE + index * 32:FONT_BASE + index * 32 + 32]
    px = [[0] * 16 for _ in range(16)]
    for blk, (ox, oy) in enumerate(((0, 0), (8, 0), (0, 8), (8, 8))):
        for y in range(8):
            for x in range(8):
                if d[blk * 8 + y] & (0x80 >> x):
                    px[oy + y][ox + x] = 1
    return px


def block_strings(rom):
    """Strings of TEXT_BLOCK: every 32-bit value in the ROM that points into the block is an
    anchor; from each anchor, strings are parsed one after the other until the next anchor or
    until the bytes are no valid string. Anchors inside an already parsed string are ignored
    (chance matches of data)."""
    lo, hi = TEXT_BLOCK
    anchors = set()
    for i in range(0, min(len(rom), 0x100000) - 3, 2):
        v = int.from_bytes(rom[i:i + 4], "big")
        if lo <= v < hi:
            anchors.add(v)
    found = {}
    covered = set()
    for a in sorted(anchors):
        if a in covered:
            continue
        p = a
        while p < hi and p not in found:
            count = rom[p] + 1
            if count > 40:
                break
            codes, end = read_codes(rom, p)
            if end > hi or any(c >= FONT_GLYPHS for c in codes):
                break
            found[p] = (codes, p in anchors)
            covered.update(range(p + 1, end))
            p = end
            if p in anchors:
                break
    return found


def unpack(rom, addr):
    """LZSS as in $007B98: word = byte budget, then flag bytes (MSB first, 1 = literal byte,
    0 = 2-byte reference: 12-bit window position, 4-bit length - 3); 4 KiB window of zeros, write
    position starts at $FEE. Returns (data, address after the packed data)."""
    budget = int.from_bytes(rom[addr:addr + 2], "big")
    p = addr + 2
    out = bytearray()
    win = bytearray(0x1000)
    w = 0xFEE
    bits = flags = 0
    while True:
        if bits == 0:
            bits, flags = 8, rom[p]
            p += 1
            budget -= 1
        bits -= 1
        literal = flags & 0x80
        flags = (flags << 1) & 0xFF
        if literal:
            run = rom[p:p + 1]
            p += 1
        else:
            ref = int.from_bytes(rom[p:p + 2], "big")
            p += 2
            budget -= 1
            run = bytearray()
            for k in range((ref & 15) + 3):
                run.append(win[((ref >> 4) + k) & 0xFFF])
                win[w] = run[-1]
                w = (w + 1) & 0xFFF
            run = bytes(run)
        if literal:
            win[w] = run[0]
            w = (w + 1) & 0xFFF
        out += run
        budget -= 1
        if budget < 0:
            return bytes(out), p


def briefing_rows(data, offset, chars):
    """Rows of the briefing entry at offset: list of text ("" = blank row), offset after it."""
    rows = []
    p = offset
    while True:
        ctrl = data[p]
        if ctrl & 0x80:
            rows.append("")
            p += 1
        else:
            codes, end = read_codes(bytes([ctrl & 0x3F]) + data[p + 1:], 0)
            rows.append(decode(codes, chars))
            p += end
        if ctrl & 0x40:
            return rows, p


def briefings(rom, chars):
    """name → (packed address, table, [(offset, [table indices], rows)])."""
    result = {}
    for name, packed, table, count in BRIEFINGS:
        data, _ = unpack(rom, packed)
        offsets = [int.from_bytes(rom[table + 2 * k:table + 2 * k + 2], "big") for k in range(count)]
        entries = []
        for o in sorted(set(offsets)):
            rows, _ = briefing_rows(data, o, chars)
            entries.append((o, [k for k, x in enumerate(offsets) if x == o], rows))
        result[name] = (packed, table, entries)
    return result


def catalog(rom, chars):
    """(section, address, format, referenced, text) for all known text."""
    rows = []
    for a, (codes, ref) in sorted(block_strings(rom).items()):
        rows.append(("block", a, "len", "ref" if ref else "seq", decode(codes, chars)))
    for section, start, count, stride, fmt in TEXT_TABLES:
        for k in range(count):
            a = start + k * stride
            if fmt == "len":
                codes, _ = read_codes(rom, a)
            else:
                codes = list(rom[a:a + int(fmt[3:])])
            rows.append((section, a, fmt, "table", decode(codes, chars).rstrip("\u3000")))
    return rows


def dump(rom, addr, lines, chars):
    for _ in range(lines):
        codes, nxt = read_codes(rom, addr)
        print(f"${addr:06X}  {decode(codes, chars)}")
        addr = nxt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("rom")
    d.add_argument("addr", nargs="+", type=lambda s: int(s.lstrip("$"), 16))
    d.add_argument("--lines", type=int, default=1)
    i = sub.add_parser("intro")
    i.add_argument("rom")
    c = sub.add_parser("catalog")
    c.add_argument("rom")
    c.add_argument("--out")
    b = sub.add_parser("briefings")
    b.add_argument("rom")
    args = ap.parse_args()
    rom = open(args.rom, "rb").read()
    chars = load_charmap()
    if args.cmd == "dump":
        for a in args.addr:
            dump(rom, a, args.lines, chars)
    elif args.cmd == "catalog":
        rows = catalog(rom, chars)
        out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
        out.write("section\taddress\tformat\tsource\ttext\n")
        for section, a, fmt, src, text in rows:
            out.write(f"{section}\t${a:06X}\t{fmt}\t{src}\t{text}\n")
        sections = {}
        for row in rows:
            n, ch = sections.get(row[0], (0, 0))
            sections[row[0]] = (n + 1, ch + len(row[4]))
        summary = ", ".join(f"{k} {n} ({ch} chars)" for k, (n, ch) in sections.items())
        print(f"{len(rows)} strings: {summary}", file=sys.stderr)
    elif args.cmd == "briefings":
        for name, (packed, table, entries) in briefings(rom, chars).items():
            for o, idx, rows in entries:
                print(f"-- {name} +${o:04X} index {','.join(map(str, idx))}")
                for row in rows:
                    print(f"   {row}")
    else:
        for site, addr, lines in INTRO_CAPTIONS:
            print(f"-- lea at ${site:06X}")
            dump(rom, addr, lines, chars)


if __name__ == "__main__":
    main()
