"""Minimal PNG reader/writer (no dependencies) for the HD tools.

write(path, w, h, rows, palette=None)
    rows: list of h rows; with palette: rows of indices (bytes/lists), palette = [(r, g, b, a?)...]
    without palette: rows of (r, g, b) or (r, g, b, a) tuples.
read(path) -> (w, h, pixels, palette)
    pixels: list of rows of indices (indexed PNG, palette = list of RGBA) or of RGBA tuples
    (palette = None). Supports 8-bit grey, grey+alpha, RGB, RGBA and 1/2/4/8-bit indexed,
    non-interlaced (what common editors write by default).
"""
import struct
import zlib


def _chunk(kind, data):
    c = kind + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)


def write(path, w, h, rows, palette=None):
    raw = bytearray()
    if palette is not None:
        hdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
        for row in rows:
            raw.append(0)
            raw += bytes(row)
        plte = b"".join(bytes(p[:3]) for p in palette)
        extra = _chunk(b"PLTE", plte)
        if any(len(p) > 3 and p[3] != 255 for p in palette):
            extra += _chunk(b"tRNS", bytes(p[3] if len(p) > 3 else 255 for p in palette))
    else:
        alpha = any(len(px) > 3 for row in rows for px in row)
        hdr = struct.pack(">IIBBBBB", w, h, 8, 6 if alpha else 2, 0, 0, 0)
        for row in rows:
            raw.append(0)
            for px in row:
                raw += bytes(px[:4] if alpha else px[:3]) if not (alpha and len(px) == 3) else bytes(px) + b"\xff"
        extra = b""
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", hdr) + extra +
                _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b""))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def read(path):
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat, palette, trns = 8, bytearray(), None, None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) + (255,) for i in range(0, n, 3)]
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    if inter:
        raise ValueError(f"{path}: interlaced PNG not supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    if depth != 8 and ctype != 3:
        raise ValueError(f"{path}: only 8-bit colour PNGs supported")
    bpp = max(1, channels * depth // 8)
    stride = (w * channels * depth + 7) // 8
    raw = zlib.decompress(bytes(idat))
    prev = bytearray(stride)
    rows = []
    for y in range(h):
        ft = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ft == 1: line[i] = (line[i] + a) & 255
            elif ft == 2: line[i] = (line[i] + b) & 255
            elif ft == 3: line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif ft == 4: line[i] = (line[i] + _paeth(a, b, c)) & 255
        prev = line
        if ctype == 3:
            per = 8 // depth
            idx = [(line[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1) for x in range(w)]
            rows.append(idx)
        elif ctype == 0:
            rows.append([(v, v, v, 255) for v in line[:w]])
        elif ctype == 4:
            rows.append([(line[2 * x], line[2 * x], line[2 * x], line[2 * x + 1]) for x in range(w)])
        elif ctype == 2:
            rows.append([tuple(line[3 * x:3 * x + 3]) + (255,) for x in range(w)])
        else:
            rows.append([tuple(line[4 * x:4 * x + 4]) for x in range(w)])
    if ctype == 3:
        if trns and palette:
            palette = [p[:3] + (trns[i] if i < len(trns) else 255,) for i, p in enumerate(palette)]
        return w, h, rows, palette
    return w, h, rows, None
