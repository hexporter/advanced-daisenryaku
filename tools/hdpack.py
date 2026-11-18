#!/usr/bin/env python3
"""HD tile pack for the 4x presentation (framework patch 0007, docs/notes/hd-graphics.md).

    tools/hdpack.py build [--out build/hd/pack.bin]     text + art → pack
    tools/hdpack.py preview TEXT... [--font big|small]  1x and 4x of a text → build/hd/preview-*.png

The runner loads the pack with GENESIS_HD_PACK (tools/run.sh sets it when build/hd/pack.bin
exists) and renders every tile it finds in the pack at 4x.

Text: the English text of the tr ROM is set by tools/translate_rom.py with text fonts drawn from
a typeface (tools/hd/typeface.py: Nunito Sans Medium, small size its condensed width; one
baseline, the typeface's own spacing; cut into 16x16 cells). This tool replays exactly that build
with the text-setting functions wrapped: every glyph column also carries its 4x columns from the
same font, so each 8x8 quarter of every cell gets its 4x shape at the same position. The game's
8x8 font (names, numbers) and the original 16x16 digits keep the game's positions; their 4x
glyphs come from the same typeface on a common baseline. Entries are "shape" entries: the game
draws glyphs in varying colours, the runner matches the two-colour 1bpp shape and keeps the
colours.

Art: indexed PNGs in hd/art/ (see docs/notes/hd-graphics.md), added as "full" entries.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adtext  # noqa: E402
import translate_rom as tr  # noqa: E402
from hd import png, typeface  # noqa: E402

ROOT = adtext.ROOT
SCALE = 4
OUT = os.path.join(ROOT, "build", "hd", "pack.bin")
FONT8_BASE = 0x03850E     # 8x8 font, 8 bytes per glyph, codes $00-$A7 as in the 16x16 font
# 8x8 glyphs left 1x: the bar and the apostrophe (identical when scaled, likely to match frame
# tiles). "．" and "：" are drawn since the typeface layout (07.11.2026): the 1x dots sat below the
# new baseline; of 3094 collected tiles only the status bar's own dot has that shape.
FONT8_SKIP = set("―’")
# One-cell symbols of both fonts set as several letters of the typeface (the
# pixel "Ⅳ" of "PzKwⅣF2" and the stacked "㎜" sat below the baseline of the letters around them).
SYMBOLS = set("ⅡⅢⅣⅥⅦⅧⅨ㎜㎏")


def config():
    env = {}
    path = os.path.join(ROOT, "config.env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = os.path.expandvars(v.strip().strip('"'))
    return env


def pixel_columns(cols, rows=16):
    """4x columns of a 1x glyph scaled pixel by pixel (characters the typeface lacks)."""
    return [sum(((c >> (y // SCALE)) & 1) << y for y in range(rows * SCALE)) for c in cols for _ in range(SCALE)]


class Col(int):
    """A 1x glyph column that also carries its SCALE 4x columns."""
    def __new__(cls, value, hd):
        o = int.__new__(cls, value)
        o.hd = hd
        return o


# ---- replaying the translation build -----------------------------------------------------

CELLS = {}       # 1x cell (32 bytes, font format, bit = ink) → {4x cell (4 quarters): count}
_orig_set_text, _orig_cells_of = tr.set_text, tr.cells_of


def set_text(text, glyphs, space=tr.SPACE_WIDTH):
    cols = _orig_set_text(text, glyphs, space)
    if not hasattr(glyphs, "hd"):
        return cols                      # game glyphs (tile pictures): no HD text
    # same algorithm as translate_rom.set_text, with columns carrying their 4x version
    spaced = getattr(glyphs, "spaced", False)
    if spaced:
        space = glyphs.space
    out = []
    for ch in text:
        if ch == " ":
            out += [0] * space
            continue
        if out and out[-1] and not spaced:
            out.append(0)
        hd = glyphs.hd(ch)
        out += [Col(c, hd[i * SCALE:(i + 1) * SCALE]) for i, c in enumerate(glyphs[ch])]
    assert [int(c) for c in out] == [int(c) for c in cols], text
    return out


QUARTERS = ((0, 0), (8, 0), (0, 8), (8, 8))   # font and VRAM order: TL TR BL BR


def hd_cell(hdcols):
    """4x quarters (TL TR BL BR, each (8*SCALE)^2 texels 0/1) from 16*SCALE 4x columns."""
    side = 8 * SCALE
    out = []
    for ox, oy in QUARTERS:
        hd = bytearray(side * side)
        for y in range(side):
            for x in range(side):
                hd[y * side + x] = (hdcols[ox * SCALE + x] >> (oy * SCALE + y)) & 1
        out.append(bytes(hd))
    return tuple(out)


def add_cell(cell, hdcols):
    cell = bytes(cell)
    if not any(cell):
        return
    hd = hd_cell(hdcols)
    CELLS.setdefault(cell, {})
    CELLS[cell][hd] = CELLS[cell].get(hd, 0) + 1


def cells_of(cols):
    cells = _orig_cells_of(cols)
    for n, cell in enumerate(cells):
        c = list(cols[n * 16:n * 16 + 16]) + [0] * 16
        hdcols = []
        for col in c[:16]:
            hdcols += col.hd if isinstance(col, Col) else [0] * SCALE
        add_cell(cell, hdcols)
    return cells


def collect_fixed(jp):
    """Original 16x16 glyphs the translation still uses as codes (digits, prefixes) and the game's
    full-width punctuation: the game's position, the typeface glyph centred on the 1x ink, on the
    big size's baseline."""
    import unicodedata
    codes = dict(tr.FIXED_CODES)
    # the game's own full-width punctuation (dates "39. 9. 1", "$", "%", ...): same treatment
    for code, ch in adtext.load_charmap().items():
        p = unicodedata.normalize("NFKC", ch)
        if len(p) == 1 and p.isascii() and not p.isalnum() and p.strip() and code not in codes.values():
            codes.setdefault(p, code)
        elif ch in SYMBOLS or ch in "ⅠⅤⅩ":
            codes[p] = code
    for ch, idx in codes.items():
        if ch == " ":
            continue
        try:
            px = adtext.glyph_bits(jp, idx)
        except (IndexError, ValueError):
            continue
        cols = [sum(px[y][x] << y for y in range(16)) for x in range(16)]
        ink = [x for x, c in enumerate(cols) if c]
        if not ink:
            continue
        hdcols = (typeface.hd_glyph("big", ch, 16, (ink[0] + ink[-1] + 1) / 2, max_width=ink[-1] - ink[0] + 1)
                  or pixel_columns(cols))
        add_cell(adtext_cell(px), hdcols)


def collect_8x8(jp):
    """Shape entries for the 8x8 font (names, numbers): 1bpp key → 4x glyph (both polarities).
    The game places these glyphs itself (8 px each); the typeface glyph is centred on the 1x ink,
    on the 8x8 size's baseline."""
    import unicodedata
    chars = adtext.load_charmap()
    shapes = {}
    for code in range(0xA8):
        ch = chars.get(code, "")
        plain = unicodedata.normalize("NFKC", ch)
        if ch in FONT8_SKIP or not plain.isascii() or not plain.strip() or (len(plain) != 1 and ch not in SYMBOLS):
            continue                     # kana and icons stay 1x
        key = bytes(jp[FONT8_BASE + code * 8:FONT8_BASE + code * 8 + 8])
        cols = [sum(((key[y] >> (7 - x)) & 1) << y for y in range(8)) for x in range(8)]
        ink = [x for x, c in enumerate(cols) if c]
        if not ink:
            continue
        if len(plain) > 1:               # a symbol: mid-cell, clear of the letters next to it
            hdcols = typeface.hd_glyph("8x8", plain, 8, 4, max_width=6.5)
        else:
            hdcols = typeface.hd_glyph("8x8", plain, 8, (ink[0] + ink[-1] + 1) / 2)
        hdcols = hdcols or pixel_columns(cols, 8)
        side = 8 * SCALE
        tex = bytes((hdcols[x] >> y) & 1 for y in range(side) for x in range(side))
        shapes.setdefault(key, tex)
        shapes.setdefault(bytes(255 - b for b in key), bytes(1 - t for t in tex))
    return shapes


def adtext_cell(px):
    data = bytearray()
    for ox, oy in QUARTERS:
        for y in range(oy, oy + 8):
            data.append(sum(px[y][ox + x] << (7 - x) for x in range(8)))
    return bytes(data)


def collect_text(jp_rom):
    tr.set_text, tr.cells_of = set_text, cells_of
    tmp = os.path.join(ROOT, "build", "hd", "replay.md")
    argv = sys.argv
    sys.argv = ["translate_rom.py", jp_rom, tmp]
    try:
        tr.main()
    finally:
        sys.argv = argv
        os.remove(tmp) if os.path.exists(tmp) else None


def text_entries():
    """Cell entries (33-byte key → 4x quarter) in both polarities; majority 4x per cell."""
    out, conflicts = {}, 0
    for cell, hds in CELLS.items():
        hd = max(hds.items(), key=lambda kv: kv[1])[0]
        conflicts += len(hds) > 1
        inv = bytes(255 - b for b in cell)
        for q in range(4):
            out[cell + bytes([q])] = hd[q]
            out.setdefault(inv + bytes([q]), bytes(1 - b for b in hd[q]))
    return out, conflicts


# ---- pack --------------------------------------------------------------------------------

def write_pack(path, cells, fulls, shapes=None):
    shapes = shapes or {}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"GHDPACK1" + struct.pack("<I", len(cells) + len(fulls) + len(shapes)))
        for key, (scale, texels) in fulls.items():
            f.write(struct.pack("<BBH", 0, scale, 0) + key + texels)
        for key, texels in cells.items():
            f.write(struct.pack("<BBH", 2, SCALE, 0) + key + bits(texels))
        for key, texels in shapes.items():
            f.write(struct.pack("<BBH", 1, SCALE, 0) + key + bits(texels))


def bits(texels):
    """0/1 texels → bytes, MSB first."""
    out = bytearray(len(texels) // 8)
    for i, t in enumerate(texels):
        if t:
            out[i >> 3] |= 0x80 >> (i & 7)
    return bytes(out)


def load_art():
    """Full entries from hd/art (filled in by hd_art.py import)."""
    fulls = {}
    path = os.path.join(ROOT, "build", "hd", "art.bin")
    if os.path.exists(path):
        d = open(path, "rb").read()
        pos = 0
        while pos < len(d):
            scale = d[pos]
            side = 8 * scale
            fulls[d[pos + 1:pos + 33]] = (scale, d[pos + 33:pos + 33 + side * side])
            pos += 33 + side * side
    return fulls


def cmd_build(args):
    jp = config().get("ROM_JP_PATH")
    if not jp or not os.path.exists(jp):
        sys.exit("ROM_JP_PATH missing in config.env")
    print("Replaying the translation build with 4x glyphs …", flush=True)
    collect_text(jp)
    collect_fixed(open(jp, "rb").read())
    cells, conflicts = text_entries()
    shapes = collect_8x8(open(jp, "rb").read())
    fulls = load_art()
    write_pack(args.out, cells, fulls, shapes)
    print(f"{args.out}: {len(CELLS)} text cells ({conflicts} with differing 4x versions, majority used), "
          f"{len(cells)} cell entries, {len(shapes) // 2} 8x8 glyphs, {len(fulls)} art tiles")


def cmd_preview(args):
    jp = open(config()["ROM_JP_PATH"], "rb").read()
    glyphs = (typeface.text_font("big", tr.brief_glyphs(jp), extra="äöüéèò'-.,") if args.font == "big"
              else typeface.text_font("small", tr.small_glyphs()))
    space = glyphs.space
    text = " ".join(args.text)
    tr.set_text = set_text
    cols = set_text(text, glyphs, space)
    w = len(cols)
    one = [[255 * ((int(c) >> y) & 1) for c in cols] for y in range(16)]
    hdc = []
    for c in cols:
        hdc += c.hd if isinstance(c, Col) else [0] * SCALE
    four = [[255 * ((c >> y) & 1) for c in hdc] for y in range(16 * SCALE)]
    big = [[one[y // SCALE][x // SCALE] for x in range(w * SCALE)] for y in range(16 * SCALE)]
    rows = [[(v, v, v) for v in r] for r in big + [[80] * (w * SCALE)] + four]
    os.makedirs(os.path.join(ROOT, "build", "hd"), exist_ok=True)
    out = os.path.join(ROOT, "build", "hd", f"preview-{args.font}.png")
    png.write(out, w * SCALE, len(rows), rows)
    print(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default=OUT)
    p = sub.add_parser("preview")
    p.add_argument("text", nargs="+")
    p.add_argument("--font", default="big", choices=["big", "small"])
    args = ap.parse_args()
    {"build": cmd_build, "preview": cmd_preview}[args.cmd](args)


if __name__ == "__main__":
    main()
