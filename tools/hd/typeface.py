"""Text fonts drawn from a real typeface instead of the game's pixel fonts (docs/notes/hd-graphics.md).

The game fonts look untidy in HD – letters fitted to the game glyphs get
different heights ("g" and "y" raised, the game font has no room for descenders) and uneven
spacing. Here the typeface sets the text itself:

  - one scale per size, chosen so capitals plus descenders fit the font's rows,
  - every glyph on one baseline, descenders below it,
  - the typeface's own advance widths (rounded to whole 1x pixels, so the 1x layout and the HD
    layout stay in register and every 1x cell still has exactly one HD version).

TextFont (a dict like translate_rom's glyph dicts: char -> 1x columns, a slot of the glyph's
advance width) also carries the 4x columns (hd) and the space width; `spaced` tells set_text
that the slots already contain the letter spacing. Characters the typeface lacks fall back to
the game glyph (pixel-scaled in HD).

Rasterizing needs macOS (CoreText via glyphs.swift); results are cached in build/hd/.
"""
import hashlib
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SWIFT = os.path.join(ROOT, "tools", "hd", "glyphs.swift")
CACHE = os.path.join(ROOT, "build", "hd")
SCALE = 4
RENDER_PX = 160
THRESHOLD_HD = 110     # grey level counted as ink at 4x (0-255)
THRESHOLD_1X = 80      # at 1x a little lower, so thin strokes do not vanish

# Nunito Sans Medium (SIL OFL 1.1, tools/hd/fonts/): chosen from nine open
# typefaces – the rendered glyphs end up in the translated ROM and the HD pack, so the typeface
# must be free to distribute (before: Avenir Next, a system font). The small size (tight boxes,
# ~4 px per letter in the game's own small font) uses the condensed width of the same family.
# A face is a font file below tools/hd/fonts/ or the PostScript name of an installed font.
# Per size: typeface, vertical room (1x rows, inclusive) and the largest cap height (1x px).
SIZES = {
    "big":   dict(face="NunitoSans-Medium-w94.ttf", top=1, bottom=15, max_cap=13),   # 16x16: menus, captions, briefings
    "small": dict(face="NunitoSansCondensed-Medium.ttf", top=5, bottom=14, max_cap=7),   # small font's rows
    "8x8":   dict(face="NunitoSans-Medium-w94.ttf", top=0, bottom=7, max_cap=7),     # game's 8x8 font: names, numbers
}
FONTS = os.path.join(ROOT, "tools", "hd", "fonts")
DESCENDERS = "gjpqy"
VERSION = 1

_raster = {}


def rasterize(face, chars, px=RENDER_PX):
    """char -> (w, h, grey bytes, left, top, advance) at px, or (0, 0, b'', 0, 0, advance) for
    glyphs without ink, or None when the face has no glyph."""
    todo = [c for c in chars if (face, px, c) not in _raster]
    if todo:
        bundled = os.path.join(FONTS, face)
        r = subprocess.run(["swift", SWIFT, bundled if os.path.exists(bundled) else face, str(px)], input="\n".join(todo) + "\n",
                           capture_output=True, text=True, check=True)
        for c, line in zip(todo, r.stdout.splitlines()):
            f = line.split(" ")
            if f[2] == "-":
                _raster[(face, px, c)] = (0, 0, b"", 0.0, 0.0, float(f[5])) if len(f) > 5 else None
            else:
                _raster[(face, px, c)] = (int(f[0]), int(f[1]), bytes.fromhex(f[2]),
                                          float(f[3]), float(f[4]), float(f[5]))
    return {c: _raster[(face, px, c)] for c in chars}


def resample(src, tw, th, threshold):
    """Area-average grey (w, h, bytes) into tw x th; returns rows of 0/1."""
    w, h, d = src
    out = []
    for ty in range(th):
        y0, y1 = ty * h / th, (ty + 1) * h / th
        row = []
        for tx in range(tw):
            x0, x1 = tx * w / tw, (tx + 1) * w / tw
            acc = area = 0.0
            for sy in range(int(y0), min(h, int(y1 + 0.999))):
                fy = min(y1, sy + 1) - max(y0, sy)
                if fy <= 0:
                    continue
                for sx in range(int(x0), min(w, int(x1 + 0.999))):
                    fx = min(x1, sx + 1) - max(x0, sx)
                    if fx <= 0:
                        continue
                    acc += d[sy * w + sx] * fx * fy
                    area += fx * fy
            row.append(1 if area and acc / area >= threshold else 0)
        out.append(row)
    return out


def metrics(face, size):
    """(scale render px -> 1x px, baseline in 1x rows as float) of a face at a size."""
    sz = SIZES[size]
    g = rasterize(face, ["H"] + list(DESCENDERS))
    cap = g["H"][4]
    desc = max(v[1] - v[4] for c, v in g.items() if c != "H" and v and v[1])
    room = sz["bottom"] + 1 - sz["top"]
    s = min(sz["max_cap"] / cap, room / (cap + desc))
    base = sz["bottom"] + 1 - desc * s          # descenders end on the last row
    return s, base


def draw(src, x, y, w_cols, rows, scale, threshold, xscale=None):
    """Glyph ink box src (w, h, grey) at (x, y) (pixels of this scale) into w_cols column masks.
    xscale: own horizontal scale (symbols squeezed into one cell)."""
    w, h, d = src
    tw, th = max(1, round(w * (xscale or scale))), max(1, round(h * scale))
    cols = [0] * w_cols
    bits = resample((w, h, d), tw, th, threshold)
    for yy in range(th):
        for xx in range(tw):
            cx, cy = x + xx, y + yy
            if bits[yy][xx] and 0 <= cx < w_cols and 0 <= cy < rows:
                cols[cx] |= 1 << cy
    return cols


class TextFont(dict):
    spaced = True

    def hd(self, ch):
        return self._hd[ch]


def _cache_path(size, chars, face):
    key = hashlib.sha1(json.dumps([VERSION, face, size, SIZES[size], RENDER_PX, THRESHOLD_HD,
                                   THRESHOLD_1X, sorted(chars)]).encode()).hexdigest()[:12]
    return os.path.join(CACHE, f"typeface-{size}-{key}.json")


def text_font(size, fallback, extra="", face=None):
    """TextFont for the 16x16 text (size "big" or "small"): the characters of fallback (the game
    glyph dict) plus extra, drawn from face; fallback glyphs for characters the face lacks."""
    face = face or SIZES[size]["face"]
    chars = sorted(set(fallback) | set(extra))
    path = _cache_path(size, chars, face)
    if os.path.exists(path):
        data = json.load(open(path))
    else:
        data = _build(size, chars, face, fallback)
        os.makedirs(CACHE, exist_ok=True)
        json.dump(data, open(path, "w"))
    f = TextFont()
    f._hd = {}
    for ch, (one, four) in data["glyphs"].items():
        if one is None:                       # not in the face: the game glyph
            one = list(fallback[ch]) + [0]
            four = [sum(((c >> (y // SCALE)) & 1) << y for y in range(16 * SCALE))
                    for c in one for _ in range(SCALE)]
        f[ch] = one
        f._hd[ch] = four
    f.space = data["space"]
    f.size = size
    return f


def _build(size, chars, face, fallback):
    s, base = metrics(face, size)
    g = rasterize(face, chars + [" "])
    out = {}
    for ch in chars:
        v = g.get(ch)
        if v is None or not v[1]:
            out[ch] = (None, None)
            continue
        w, h, d, left, top, adv = v
        slot = max(1, round(adv * s))
        one = draw((w, h, d), round(left * s), round(base - top * s), slot, 16, s, THRESHOLD_1X)
        four = draw((w, h, d), round(left * s * SCALE), round((base - top * s) * SCALE),
                    slot * SCALE, 16 * SCALE, s * SCALE, THRESHOLD_HD)
        if not any(one):                      # too thin at 1x: keep the 4x ink's footprint
            one = [1 << (base_row(base) - 1) if any(four[i * SCALE:(i + 1) * SCALE]) else 0 for i in range(slot)]
        out[ch] = (one, four)
    sp = g[" "]
    return {"glyphs": out, "space": max(1, round((sp[5] if sp else 0.28 / s) * s))}


def base_row(base):
    return int(round(base))


def compose(face, text):
    """Several letters set as one glyph (w, h, grey, left, top, advance) – for the game's
    one-cell symbols ("Ⅲ" = "III", "㎜" = "mm"); None if the face lacks a letter."""
    g = rasterize(face, list(text))
    if any(g[c] is None for c in text):
        return None
    pen, boxes = 0.0, []
    for c in text:
        w, h, d, left, top, adv = g[c]
        if h:
            boxes.append((round(pen + left), round(top), w, h, d))
        pen += adv
    if not boxes:
        return None
    x0, x1 = min(b[0] for b in boxes), max(b[0] + b[2] for b in boxes)
    t, b = max(b[1] for b in boxes), min(b[1] - b[3] for b in boxes)
    w, h = x1 - x0, t - b
    out = bytearray(w * h)
    for bx, bt, bw, bh, d in boxes:
        for y in range(bh):
            o = (t - bt + y) * w + bx - x0
            for x in range(bw):
                out[o + x] = max(out[o + x], d[y * bw + x])
    return w, h, bytes(out), float(x0), float(t), pen


def hd_glyph(size, ch, width, centre, face=None, max_width=None):
    """4x columns (width*SCALE columns) of ch for a glyph the game places itself (8x8 font,
    the original 16x16 digits): centred on centre (1x px), on the size's baseline; None if the
    face has no glyph. Several letters (a one-cell symbol such as "III" or "mm") are set as one
    glyph, at the size's height and squeezed to max_width (1x px) – in the condensed cut when
    the regular one is too wide."""
    face = face or SIZES[size]["face"]
    s, base = metrics(face, size)
    if len(ch) > 1:
        v = compose(face, ch)
        if v and max_width and v[0] * s > max_width:
            v = compose(SIZES["small"]["face"], ch) or v
    else:
        v = rasterize(face, [ch]).get(ch)
    if v is None or not v[1]:
        return None
    w, h, d, left, top, adv = v
    rows = (SIZES[size]["bottom"] + 1 if size == "8x8" else 16) * SCALE
    k = s * SCALE
    # glyphs taller than the row ("$", brackets reach above the capitals) shrink to fit,
    # still standing on the baseline ("$" was cut off in the status bar)
    above, below = top * k, (h - top) * k
    if above > base * SCALE:
        k *= base * SCALE / above
    if below > 0 and (h - top) * k > rows - base * SCALE:
        k *= (rows - base * SCALE) / ((h - top) * k)
    kx = k
    if len(ch) > 1 and max_width and w * kx > max_width * SCALE:
        kx = max_width * SCALE / w
    tw = round(w * kx)
    x = round(centre * SCALE - tw / 2)
    x = min(max(0, x), width * SCALE - tw) if tw <= width * SCALE else 0
    return draw((w, h, d), x, round(base * SCALE - top * k), width * SCALE, rows, k, THRESHOLD_HD, kx)
