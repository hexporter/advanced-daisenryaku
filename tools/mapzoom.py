#!/usr/bin/env python3
"""Zoomed-out hex map: render the whole map from game RAM + ROM (prototype, docs/notes/map.md).

The game itself only draws the hexes around its view into the VDP planes. This tool redraws any
part of the map the way the game would, from:
  - RAM ($FF0000-$FFFFFF): terrain $FFA000, fog/range flags $FF7000, units $FFB000, view $FFCD20
  - ROM: hex block tables (model of $012EDA), unit graphics (model of $012B3A)
  - VRAM/CRAM of the map screen: terrain tile patterns (loaded for the map), palette

Usage:
    tools/mapzoom.py render RAM VDP.json OUT.png [--rom ROM] [--area view|zoom|map] [--scale N]
    tools/mapzoom.py check RAM VDP.json SCREEN.png [--rom ROM]

RAM = 64 KiB dump of $FF0000 (debug server read_memory), VDP.json = debug server
vdp_state with include="vram,cram,vsram", SCREEN.png = debug server screenshot (1x).
`check` renders the game's own view and compares it with the screenshot pixel by pixel.
"""
import argparse
import json
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "hd"))
import png  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROM = os.path.join(ROOT, "build", "rom", "ad-tr.md")

# ---- ROM addresses (docs/notes/map.md) ----
SEASON_TABLES = 0x013214   # 6 pointers: terrain code -> graphic byte, per $CDAB
CLASS_MASKS = 0x0130FC     # 32-bit join class per terrain code
NBR_ODD = 0x0130D8         # 6 neighbour offsets, odd Y
NBR_EVEN = 0x0130E4        # 6 neighbour offsets, even Y
PLAIN_BLOCKS = 0x038332    # 6 words per graphic
JOIN_BLOCKS = 0x04342A     # $300 per graphic, 12 bytes per neighbour mask
UNIT_TYPES = 0x02B1F2      # $22 bytes per type, +$14 = graphic
UNIT_GFX = 0x05B42A        # 6 tile numbers per graphic
UNIT_PATTERNS = 0x04852A   # 4bpp tiles
UNIT_MASK = 0x039F5E       # $C0 per mark variant (AND)
UNIT_OVER = 0x039A1E       # $C0 per mark variant (OR)
SPRITE_TERRAIN = 0x012AF4  # terrain codes whose plane A has an overlay -> unit as sprite


class Game:
    def __init__(self, rom, ram, vdp):
        self.rom, self.ram = rom, ram
        self.vram = bytes.fromhex(vdp["vram"])
        self.cram = vdp["cram"]

    def w(self, a): return struct.unpack(">H", self.rom[a:a + 2])[0]
    def l(self, a): return struct.unpack(">I", self.rom[a:a + 4])[0]
    def s16(self, a): return struct.unpack(">h", self.rom[a:a + 2])[0]
    def terr(self, i): return self.ram[0xA000 + (i & 0xFFF)]

    def mask(self, code):
        d = self.l(CLASS_MASKS + code * 4)
        return (d & 0xFF00FFFF) | ((d >> 24) << 16)

    def nbrs(self, y):
        base = NBR_ODD if y & 1 else NBR_EVEN
        return [self.s16(base + 2 * k) for k in range(6)]

    # ---- $012EDA: one hex -> 6 plane B words, 6 plane A words (TL TM TR BL BM BR) ----
    def hex_words(self, x, y):
        idx = y * 64 + x
        code = self.terr(idx) & 0x7F
        g = self.rom[self.l(SEASON_TABLES + self.ram[0xCDAB] * 4) + code]
        cls = 0
        if g & 0x80:
            cls = self.mask(code)
            n = 0
            for o in self.nbrs(y):
                n = (n << 1) & 0xFFFF
                if cls & self.mask(self.terr(idx + o) & 0x7F) == 0:
                    n |= 1
            blk = JOIN_BLOCKS + (g & 0x7F) * 0x300 + n * 12
        else:
            blk = PLAIN_BLOCKS + g * 12
        b = [self.w(blk + 2 * k) for k in range(6)]
        d0 = 0x8000 if self.ram[0x7000 + idx] & 0x40 else 0
        if cls & 0x80000000:
            offs = self.nbrs(y)
            m = 0x60300 if cls & 0x20000000 else 0x80002
            side = 0
            for k in range(3):
                if m & self.mask(self.terr(idx + offs[k]) & 0x7F):
                    side = 2 - k
                    break
            d0 += side * 6 + (0x25E3 if cls & 0x20000000 else 0x25BF)
            if cls & 0x10000000:
                d0 += 0x12
            a = [d0, d0 + 2, d0 + 4, d0 + 1, d0 + 3, d0 + 5]
        elif self.ram[0xCC25]:
            a = [d0] * 6
        else:
            d0 += 0x3C8
            a = [d0, d0 + 2, d0 + 4, d0 + 1, d0 + 3, d0 + 5]
        return b, a

    # ---- $012D4A / $012B3A: units ----
    def units(self):
        for n in range(256):
            r = self.ram[0xB000 + n * 0x18:0xB018 + n * 0x18]
            if r[0] & 0x80 or r[4] & 0x10 or r[0x10] & 0x80:   # Y bit 7: moving (sprite)
                continue
            yield r

    def unit_tiles(self, r):
        """6 composed 4bpp tiles in plane order TL TM TR BL BM BR, and the palette line."""
        typ = struct.unpack(">H", r[2:4])[0]
        gfx = self.w(UNIT_TYPES + typ * 0x22 + 0x14)
        v = (1 if r[4] & 0x80 else 0) + (2 if r[4] & 0x20 else 0)
        nogrid = self.ram[0xCC25] != 0
        col_major = []
        for k in range(6):
            src = UNIT_PATTERNS + self.w(UNIT_GFX + gfx * 12 + 2 * k) * 32
            data = self.rom[src:src + 32]
            if not (nogrid and v == 0):
                vv = v + 3 if nogrid else v
                m = self.rom[UNIT_MASK + vv * 0xC0 + 32 * k:][:32]
                o = self.rom[UNIT_OVER + vv * 0xC0 + 32 * k:][:32]
                data = bytes((p & q) | s for p, q, s in zip(data, m, o))
            col_major.append(data)
        order = [col_major[c * 2 + rr] for rr in (0, 1) for c in (0, 1, 2)]
        return order, r[0x0F] >> 1

    # ---- composition ----
    def vram_px(self, word, fx, fy):
        t = word & 0x7FF
        if word & 0x800: fx = 7 - fx
        if word & 0x1000: fy = 7 - fy
        b = self.vram[t * 32 + fy * 4 + fx // 2]
        return (b >> 4) if fx % 2 == 0 else b & 15

    def render(self, x0, y0, w, h, stagger_odd=True, cursor=True):
        """Palette index image (0-63, +64 = shadow) of the map area at map pixels (x0, y0).

        Map pixel of hex (X, Y): x = 24*X (+12 on staggered rows), y = 16*Y."""
        ia = [[(0, 0, 0)] * w for _ in range(h)]   # (colour index, priority, opaque) plane A
        ib = [[(0, 0, 0)] * w for _ in range(h)]
        sp = [[None] * w for _ in range(h)]          # sprites: (colour index, priority)
        unit_at = {}
        for r in self.units():
            unit_at[(r[1], r[0])] = r

        def hexpos(X, Y):
            return 24 * X + (12 if (Y & 1) == stagger_odd else 0), 16 * Y

        def put_tile(layer, px, py, pattern, word):
            pal, prio = (word >> 13) & 3, word >> 15
            for fy in range(8):
                yy = py + fy - y0
                if not 0 <= yy < h: continue
                for fx in range(8):
                    xx = px + fx - x0
                    if not 0 <= xx < w: continue
                    n = pattern(fx, fy, word)
                    if layer is sp:
                        if n: sp[yy][xx] = (pal * 16 + n, prio)
                    else:
                        layer[yy][xx] = (pal * 16 + n, prio, n != 0)

        vram_pat = lambda fx, fy, word: self.vram_px(word, fx, fy)
        for Y in range(64):
            for X in range(64):
                px, py = hexpos(X, Y)
                if px + 24 < x0 or px >= x0 + w or py + 16 < y0 or py >= y0 + h:
                    continue
                if self.terr(Y * 64 + X) & 0x80:
                    continue
                b, a = self.hex_words(X, Y)
                for k in range(6):
                    put_tile(ib, px + 8 * (k % 3), py + 8 * (k // 3), vram_pat, b[k])
                r = unit_at.get((X, Y))
                if r is None:
                    for k in range(6):
                        put_tile(ia, px + 8 * (k % 3), py + 8 * (k // 3), vram_pat, a[k])
                    continue
                tiles, pal = self.unit_tiles(r)
                vis = 0x8000 if self.ram[0x7000 + Y * 64 + X] & 0x40 else 0
                as_sprite = self.rom[SPRITE_TERRAIN + (self.terr(Y * 64 + X) & 0x7F)] != 0
                for k in range(6):
                    pat = (lambda t: (lambda fx, fy, word: (t[fy * 4 + fx // 2] >> (4 * (1 - fx % 2))) & 15))(tiles[k])
                    word = vis | (pal << 13)
                    if as_sprite:
                        put_tile(ia, px + 8 * (k % 3), py + 8 * (k // 3), vram_pat, a[k])
                        put_tile(sp, px + 8 * (k % 3), py + 8 * (k // 3), pat, word)
                    else:
                        put_tile(ia, px + 8 * (k % 3), py + 8 * (k // 3), pat, word)
        if cursor:
            cx = self.ram[0xCD1E] + self.ram[0xCD20]
            cy = self.ram[0xCD1F] + self.ram[0xCD21]
            px, py = hexpos(cx, cy)
            for k in range(16):    # 4x4 sprite, tile $8001, column-major
                word = 0x8001 + k
                put_tile(sp, px - 8 + 8 * (k // 4), py - 8 + 8 * (k % 4), vram_pat, word)
        out = []
        for yy in range(h):
            row = []
            for xx in range(w):
                ca, pa, oa = ia[yy][xx]
                cb, pb, ob = ib[yy][xx]
                s = sp[yy][xx]
                if s and (s[1] or not (pa or pb)):
                    c = s[0]
                elif oa and (pa or not pb):
                    c = ca
                elif ob:
                    c = cb
                elif s:
                    c = s[0]
                elif oa:
                    c = ca
                else:
                    c = 0
                hi = pa or pb or (s is not None and s[1])
                row.append(c + (0 if hi else 64))
            out.append(row)
        return out

    def rgb(self, idx):
        """Approximate RGB of a palette index (shadow = half), for viewing only."""
        c = self.cram[idx & 63]
        k = 0.5 if idx & 64 else 1.0
        return tuple(int(((c >> s) & 7) * 36 * k) for s in (1, 5, 9))


def load(args):
    rom = open(args.rom, "rb").read()
    ram = open(args.ram, "rb").read()
    vdp = json.load(open(args.vdp))
    vdp = vdp.get("vdp", vdp)
    return Game(rom, ram, vdp)


def map_bounds(g):
    xs, ys = [], []
    for i in range(4096):
        if not g.ram[0xA000 + i] & 0x80:
            xs.append(i % 64); ys.append(i // 64)
    return min(xs), min(ys), max(xs), max(ys)


def read_rgb(path):
    d = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, check=True).stdout
    return d


def cmd_check(args):
    g = load(args)
    scr = read_rgb(args.screen)
    W = 320
    X0, Y0 = g.ram[0xCD20], g.ram[0xCD21]
    # map area of the screen: x 32..303 (edge mask sprites outside), y 8..167 (frame, status bar)
    sx0, sx1, sy0, sy1 = 32, 304, 8, 168
    # screen = map - (24*X0 - 10, 16*Y0 - 8): hex Y0 is plane row 1 (copy window $0059BE),
    # hscroll rows alternate by 12 px (checked on 9 captures)
    mx0, my0 = 24 * X0 - 10, 16 * Y0 - 8
    img = g.render(mx0, my0, 320, 224)
    ox = oy = 0
    pairs = {}
    for y in range(sy0, sy1):
        for x in range(sx0, sx1):
            k = img[y + oy][x + ox]
            o = (y * W + x) * 3
            pairs.setdefault(k, {}).setdefault(bytes(scr[o:o + 3]), []).append((x, y))
    conflicts, by_key = [], {}
    for k, cs in pairs.items():
        main = max(cs, key=lambda c: len(cs[c]))
        for c, pts in cs.items():
            if c != main:
                conflicts += pts
                by_key[k] = by_key.get(k, 0) + len(pts)
    total = (sx1 - sx0) * (sy1 - sy0)
    print("screen = map - (%d, %d)  (view origin %d,%d)" % (mx0, my0, X0, Y0))
    print("pixels %d, colour keys %d, pixels off the majority colour of their key: %d" %
          (total, len(pairs), len(conflicts)))
    if conflicts:
        xs = [p[0] for p in conflicts]; ys = [p[1] for p in conflicts]
        print("  in x %d-%d, y %d-%d" % (min(xs), max(xs), min(ys), max(ys)))
        print("  by colour (palette line.entry, s = shadow): " + ", ".join(
            "%d.%d%s: %d" % ((k & 63) >> 4, k & 15, "s" if k & 64 else "", n) for k, n in sorted(by_key.items())))
        print("  (expected: open menus/windows, the right edge x >= 298 that the game does not draw,"
              " and palette 3.7-3.12, the water colours the game cycles every 16 frames)")
    return 0 if not conflicts else 1


def cmd_render(args):
    g = load(args)
    if args.area == "map":
        mx0, my0, mx1, my1 = map_bounds(g)
        x0, y0, w, h = 24 * mx0, 16 * my0, 24 * (mx1 - mx0 + 1) + 12, 16 * (my1 - my0 + 1)
    else:
        # the game's map viewport: screen x 32..303, y 8..167 = map - (24*X0 - 10, 16*Y0 - 8)
        X0, Y0 = g.ram[0xCD20], g.ram[0xCD21]
        vx, vy, vw, vh = 24 * X0 + 22, 16 * Y0, 272, 160
        f = 1 if args.area == "view" else 2      # zoom: twice the hexes in each direction
        w, h = vw * f, vh * f
        x0, y0 = vx + vw // 2 - w // 2, vy + vh // 2 - h // 2
    img = g.render(x0, y0, w, h, cursor=not args.no_cursor)
    S = args.scale
    rows = []
    for row in img:
        line = [g.rgb(i) for i in row for _ in range(S)]
        rows += [line] * S
    png.write(args.out, w * S, h * S, rows)
    print("wrote %s (%dx%d map pixels from %d,%d)" % (args.out, w, h, x0, y0))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("render", "check"):
        p = sub.add_parser(name)
        p.add_argument("ram"); p.add_argument("vdp")
        p.add_argument("screen" if name == "check" else "out")
        p.add_argument("--rom", default=DEFAULT_ROM)
        if name == "render":
            p.add_argument("--area", choices=("view", "zoom", "map"), default="zoom")
            p.add_argument("--scale", type=int, default=1)
            p.add_argument("--no-cursor", action="store_true")
    args = ap.parse_args()
    return {"render": cmd_render, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
