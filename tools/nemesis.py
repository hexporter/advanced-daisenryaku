#!/usr/bin/env python3
"""Nemesis tile compression as used by the game's decompressor at $005B1E (docs/notes/graphics.md).

Format: word header (bit 15 = XOR mode, bits 0-14 = tile count), then the code table, then the
bit stream. Each table entry describes a run "nibble × count" (count 1-8) and its prefix code
(1-8 bits): a byte >= $80 sets the nibble (bits 0-3), then pairs of bytes give count − 1 (bits 4-6)
and code length (bits 0-3) followed by the code; $FF ends the table. In the stream the code
111111 is followed by 3 bits count − 1 and 4 bits nibble (inline run). Nibbles fill 32-bit rows;
in XOR mode each row is XORed with the previous output row. Runs may cross rows.

    nemesis.py unpack ROM ADDR OUT      decompress the data at ADDR to raw tiles
    nemesis.py pack IN OUT              compress raw tiles (multiple of 32 bytes)
"""
import argparse
import heapq
import sys

INLINE = (6, 0x3F)


def unpack(rom, addr):
    """Decompress at addr; returns (tile data, end address of the stream)."""
    p = addr
    hdr = int.from_bytes(rom[p:p + 2], "big")
    p += 2
    xor, rows_total = bool(hdr & 0x8000), (hdr & 0x7FFF) * 8
    codes = {}
    nib = 0
    b = rom[p]
    p += 1
    while b != 0xFF:
        if b & 0x80:
            nib = b & 0x0F
        else:
            codes[(b & 0x0F, rom[p])] = (nib, (b >> 4) & 7)
            p += 1
        b = rom[p]
        p += 1
    pos, buf, left = p, 0, 0

    def bits(n):
        nonlocal pos, buf, left
        v = 0
        for _ in range(n):
            if not left:
                buf, left = rom[pos], 8
                pos += 1
            left -= 1
            v = (v << 1) | ((buf >> left) & 1)
        return v

    nibbles, rows, prev = [], [], 0
    while len(rows) < rows_total:
        code = length = 0
        while True:
            code, length = (code << 1) | bits(1), length + 1
            if (length, code) in codes:
                n, cnt = codes[(length, code)]
                break
            if (length, code) == INLINE:
                cnt = bits(3)
                n = bits(4)
                break
            if length >= 8:
                raise ValueError(f"invalid code at ${pos:06X}")
        nibbles += [n] * (cnt + 1)
        while len(nibbles) >= 8 and len(rows) < rows_total:
            v = 0
            for k in nibbles[:8]:
                v = (v << 4) | k
            del nibbles[:8]
            if xor:
                prev ^= v
                v = prev
            rows.append(v)
    return b"".join(r.to_bytes(4, "big") for r in rows), pos


def _runs(data):
    nibbles = [n for b in data for n in (b >> 4, b & 0x0F)]
    runs, i = [], 0
    while i < len(nibbles):
        j = i
        while j + 1 < len(nibbles) and nibbles[j + 1] == nibbles[i] and j + 1 - i < 8:
            j += 1
        runs.append((nibbles[i], j - i))
        i = j + 1
    return runs


def _lengths(freq):
    """Huffman code lengths, limited to 8 bits. An escape leaf (the symbols left inline) of depth
    <= 6 keeps the 6-bit inline code 111111 free: it gets the all-ones code of its depth."""
    syms = sorted(freq, key=lambda s: -freq[s])
    esc = None
    while syms:
        inline = sum(freq[s] for s in freq if s not in syms)
        leaves = syms + [esc]
        weight = {s: freq[s] for s in syms}
        weight[esc] = max(inline, 1)
        heap = [(weight[s], k, [s]) for k, s in enumerate(leaves)]
        heapq.heapify(heap)
        depth = {s: 0 for s in leaves}
        k = len(heap)
        while len(heap) > 1:
            f1, _, a = heapq.heappop(heap)
            f2, _, b = heapq.heappop(heap)
            for s in a + b:
                depth[s] += 1
            heapq.heappush(heap, (f1 + f2, k, a + b))
            k += 1
        if max(depth.values()) <= 8 and depth[esc] <= 6:
            del depth[esc]
            return depth
        syms.pop()          # least frequent symbol goes inline
    return {}


def pack(data):
    """Compress tiles; plain or XOR mode, whichever is smaller."""
    return min((_pack(data, False), _pack(data, True)), key=len)


def _pack(data, xor):
    assert len(data) % 32 == 0
    raw = data
    if xor:
        rows = [int.from_bytes(data[i:i + 4], "big") for i in range(0, len(data), 4)]
        raw = b"".join((r ^ (rows[k - 1] if k else 0)).to_bytes(4, "big") for k, r in enumerate(rows))
    runs = _runs(raw)
    freq = {}
    for r in runs:
        freq[r] = freq.get(r, 0) + 1
    depth = _lengths(freq)
    # Canonical codes, shortest first: the codes count up from 0, so the all-ones end of the
    # code space (the escape leaf's room) stays free for the inline code.
    code, prev_len, table = 0, 0, {}
    for s in sorted(depth, key=lambda s: (depth[s], s)):
        code <<= depth[s] - prev_len
        prev_len = depth[s]
        table[s] = (depth[s], code)
        code += 1
    out = bytearray(((0x8000 if xor else 0) | len(data) // 32).to_bytes(2, "big"))
    for nib in range(16):
        ent = sorted((s, v) for s, v in table.items() if s[0] == nib)
        if ent:
            out.append(0x80 | nib)
            for (n, cnt), (ln, c) in ent:
                out += bytes([(cnt << 4) | ln, c])
    out.append(0xFF)
    acc, nbits = 0, 0
    for s in runs:
        if s in table:
            ln, c = table[s]
            acc, nbits = (acc << ln) | c, nbits + ln
        else:
            acc, nbits = (acc << 13) | (0x3F << 7) | (s[1] << 4) | s[0], nbits + 13
        while nbits >= 8:
            nbits -= 8
            out.append((acc >> nbits) & 0xFF)
        acc &= (1 << nbits) - 1
    if nbits:
        out.append((acc << (8 - nbits)) & 0xFF)
    if len(out) & 1:
        out.append(0)
    assert unpack(bytes(out), 0)[0] == data, "pack/unpack round trip failed"
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unpack")
    u.add_argument("rom")
    u.add_argument("addr")
    u.add_argument("out")
    k = sub.add_parser("pack")
    k.add_argument("inp")
    k.add_argument("out")
    args = ap.parse_args()
    if args.cmd == "unpack":
        data, end = unpack(open(args.rom, "rb").read(), int(args.addr.lstrip("$"), 16))
        open(args.out, "wb").write(data)
        print(f"{len(data) // 32} tiles, stream ends at ${end:06X}")
    else:
        data = open(args.inp, "rb").read()
        packed = pack(data)
        open(args.out, "wb").write(packed)
        print(f"{len(data) // 32} tiles → {len(packed)} bytes")


if __name__ == "__main__":
    sys.exit(main())
