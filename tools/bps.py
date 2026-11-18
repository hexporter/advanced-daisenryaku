#!/usr/bin/env python3
"""BPS patches (the common ROM patch format, e.g. Floating IPS / beat): create, apply, show.

    tools/bps.py create SOURCE TARGET PATCH   patch that turns SOURCE into TARGET
    tools/bps.py apply  SOURCE PATCH TARGET   apply it (checks all three CRC32 values)
    tools/bps.py info   PATCH                 sizes, CRC32 values, share of literal bytes

Used by tools/release.sh: the release contains no ROM, only the patch from the JP ROM to the
translated one; the app applies it on the player's Mac (release/macos/launcher.c has the same
applier in C). Format and reasons: docs/notes/release.md
"""
import sys
import zlib

MIN_COPY = 16    # shortest match taken as a copy from the source
MIN_RUN = 8      # shortest run of one byte value taken as a copy from the target itself
GRAM = 8


def varint(n):
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def create(src, tgt):
    index = {}
    for i in range(len(src) - GRAM, -1, -1):   # backwards: the lowest offset wins
        index[src[i:i + GRAM]] = i
    out = bytearray(b"BPS1" + varint(len(src)) + varint(len(tgt)) + varint(0))
    literal = bytearray()
    src_rel = tgt_rel = 0

    def flush():
        if literal:
            out.extend(varint((len(literal) - 1) << 2 | 1))
            out.extend(literal)
            literal.clear()

    def signed(delta):
        return varint(abs(delta) << 1 | (1 if delta < 0 else 0))

    def match_len(a, b):   # common length of src[a:] and tgt[b:]
        n, step = 0, 4096
        while src[a + n:a + n + step] == tgt[b + n:b + n + step] and a + n < len(src) and b + n < len(tgt):
            n += min(step, len(src) - a - n, len(tgt) - b - n)
        while a + n < len(src) and b + n < len(tgt) and src[a + n] == tgt[b + n]:
            n += 1
        return n

    i = 0
    while i < len(tgt):
        n = match_len(i, i) if i < len(src) else 0
        if n >= 4:                                   # same bytes at the same place
            flush()
            out.extend(varint((n - 1) << 2 | 0))
            i += n
            continue
        run = 1
        while i + run < len(tgt) and tgt[i + run] == tgt[i]:
            run += 1
        if run >= MIN_RUN:                           # one literal byte, the rest copied from it
            literal.append(tgt[i])
            flush()
            out.extend(varint((run - 2) << 2 | 3))
            out.extend(signed(i - tgt_rel))
            tgt_rel = i + run - 1
            i += run
            continue
        at = index.get(tgt[i:i + GRAM])
        if at is not None:
            n = match_len(at, i)
            if n >= MIN_COPY:                        # same bytes elsewhere in the source
                flush()
                out.extend(varint((n - 1) << 2 | 2))
                out.extend(signed(at - src_rel))
                src_rel = at + n
                i += n
                continue
        literal.append(tgt[i])
        i += 1
    flush()
    out.extend(zlib.crc32(src).to_bytes(4, "little"))
    out.extend(zlib.crc32(tgt).to_bytes(4, "little"))
    out.extend(zlib.crc32(out).to_bytes(4, "little"))
    return bytes(out)


class Reader:
    def __init__(self, data):
        self.d, self.p = data, 0

    def varint(self):
        n, shift = 0, 1
        while True:
            x = self.d[self.p]
            self.p += 1
            n += (x & 0x7F) * shift
            if x & 0x80:
                return n
            shift <<= 7
            n += shift

    def signed(self):
        v = self.varint()
        return -(v >> 1) if v & 1 else v >> 1


def parse(patch):
    """-> (source size, target size, source crc, target crc, reader at the first action, end)"""
    if patch[:4] != b"BPS1" or len(patch) < 19:
        raise ValueError("not a BPS patch")
    if zlib.crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise ValueError("patch file is damaged (CRC32)")
    r = Reader(patch)
    r.p = 4
    ssize, tsize, meta = r.varint(), r.varint(), r.varint()
    r.p += meta
    return (ssize, tsize, int.from_bytes(patch[-12:-8], "little"),
            int.from_bytes(patch[-8:-4], "little"), r, len(patch) - 12)


def apply(src, patch, stats=None):
    ssize, tsize, scrc, tcrc, r, end = parse(patch)
    if len(src) != ssize or zlib.crc32(src) != scrc:
        raise ValueError("wrong source file (size or CRC32)")
    out = bytearray()
    src_rel = tgt_rel = 0
    while r.p < end:
        v = r.varint()
        kind, n = v & 3, (v >> 2) + 1
        if stats is not None:
            stats[kind] = stats.get(kind, 0) + n
        if kind == 0:
            out.extend(src[len(out):len(out) + n])
        elif kind == 1:
            out.extend(patch[r.p:r.p + n])
            r.p += n
        elif kind == 2:
            src_rel += r.signed()
            out.extend(src[src_rel:src_rel + n])
            src_rel += n
        else:
            tgt_rel += r.signed()
            for _ in range(n):
                out.append(out[tgt_rel])
                tgt_rel += 1
    if len(out) != tsize or zlib.crc32(out) != tcrc:
        raise ValueError("result does not match the patch (size or CRC32)")
    return bytes(out)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def main():
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == "create":
        src, tgt = read(a[1]), read(a[2])
        patch = create(src, tgt)
        if apply(src, patch) != tgt:
            sys.exit("internal error: patch does not reproduce the target")
        with open(a[3], "wb") as f:
            f.write(patch)
        print(f"{a[3]}: {len(patch)} bytes, source CRC32 {zlib.crc32(src):08X}, target CRC32 {zlib.crc32(tgt):08X}")
    elif len(a) == 4 and a[0] == "apply":
        out = apply(read(a[1]), read(a[2]))
        with open(a[3], "wb") as f:
            f.write(out)
        print(f"{a[3]}: {len(out)} bytes, CRC32 {zlib.crc32(out):08X}")
    elif len(a) == 2 and a[0] == "info":
        patch = read(a[1])
        ssize, tsize, scrc, tcrc, r, end = parse(patch)
        stats = {}
        while r.p < end:
            v = r.varint()
            kind, n = v & 3, (v >> 2) + 1
            stats[kind] = stats.get(kind, 0) + n
            if kind == 1:
                r.p += n
            elif kind >= 2:
                r.signed()
        print(f"source {ssize} bytes, CRC32 {scrc:08X}; target {tsize} bytes, CRC32 {tcrc:08X}")
        for kind, name in enumerate(("same place in source", "literal (in the patch)",
                                     "copied from source", "copied from target (runs)")):
            print(f"  {name:28s}{stats.get(kind, 0):9d} bytes")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as e:
        sys.exit(f"bps.py: {e}")
