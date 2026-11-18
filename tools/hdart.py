#!/usr/bin/env python3
"""HD art: collect the game's tiles, export them as sheets to redraw at 4x, import the redraws.
docs/notes/hd-graphics.md

    tools/hdart.py watch [--port 4390] [--interval 0.5]   collect tiles while the game runs
    tools/hdart.py add SNAPSHOT.json ...                  collect from saved vdp_state dumps
    tools/hdart.py export                                 new tiles → assets/hd/sheets/*.png
    tools/hdart.py import                                 redrawn tiles → build/hd/art.bin
    tools/hdart.py status                                 counts: collected, exported, redrawn

Collect needs the runner's debug server (debug.ini, as for textscan.py: tools/textscan.py debug on).

Everything lives in assets/hd/ (not in the repository: the tiles are extracted from the ROM):
  catalog.json        every distinct 8x8 pattern seen, and the "scenes" it was first seen in: one
                      scene = one screen layer (plane A, plane B or sprites) of one snapshot,
                      40x28 cells with tile and palette row
  sheets/NNN-<layer>.png   one sheet per scene, 1280x896 = the screen at 4x, holding only the tiles
                      first seen in that scene (everything else blank), so pictures stay whole.
                      Indexed PNG with the scene's 64 colours (4 palette rows of 16, index 16*row
                      + colour; colour 0 of each row = transparent). Draw over the enlarged
                      original pixels and use only colours from the tile's own palette row - or
                      save as RGB(A): colours are mapped to the nearest colour of the tile's row,
                      alpha 0 to transparent.
  sheets/index.json   which pattern sits in which cell of which sheet

Import compares every cell with the plain 4x enlargement of its original: unchanged cells are
skipped, changed cells become 4x tiles in the pack (tools/hdpack.py build reads build/hd/art.bin).
Text tiles are left out of the export: tools/hdpack.py draws them from typefaces.
"""
import argparse
import json
import os
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hd import png  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets", "hd")
CATALOG = os.path.join(ASSETS, "catalog.json")
SHEETS = os.path.join(ASSETS, "sheets")
INDEX = os.path.join(SHEETS, "index.json")
ART_BIN = os.path.join(ROOT, "build", "hd", "art.bin")
PACK = os.path.join(ROOT, "build", "hd", "pack.bin")
SCALE = 4
SIDE = 8 * SCALE


# ---- catalog ---------------------------------------------------------------------------

def load_catalog():
    if os.path.exists(CATALOG):
        return json.load(open(CATALOG))
    return {"tiles": {}}


def save_catalog(cat):
    os.makedirs(ASSETS, exist_ok=True)
    tmp = CATALOG + ".tmp"
    json.dump(cat, open(tmp, "w"), indent=0, sort_keys=True)
    os.replace(tmp, CATALOG)


def word(vram, a):
    return vram[a & 0xFFFF] << 8 | vram[(a + 1) & 0xFFFF]


def colours(pattern):
    return {b >> 4 for b in pattern} | {b & 15 for b in pattern}


SCREEN_W, SCREEN_H = 40, 28      # cells (H40)


def add_snapshot(cat, vdp, name=""):
    """Record every tile on screen (planes A/B through their scroll, sprites at their position)
    with its palette row. Tiles seen for the first time are assigned to a new scene."""
    if not vdp.get("display", 1):
        return 0
    vram = bytes.fromhex(vdp["vram"]) if isinstance(vdp["vram"], str) else bytes(vdp["vram"])
    cram = vdp["cram"]
    if isinstance(cram, str):
        cram = [int(cram[i:i + 4], 16) for i in range(0, len(cram), 4)]
    if len(set(c & 0xEEE for c in cram)) <= 1:
        return 0                                     # fade / blank palette
    vsram = vdp["vsram"]
    if isinstance(vsram, str):
        vsram = [int(vsram[i:i + 4], 16) for i in range(0, len(vsram), 4)]
    pw, ph = 1 << vdp["plane_w_shift"], vdp["plane_h_mask"] + 1
    hs_base, hs_mode = vdp["hscroll"], vdp["hscroll_mask"]

    def hscroll(line, plane):
        line = 0 if hs_mode == 0 else line & ~7 if hs_mode == 2 else line
        return word(vram, hs_base + line * 4 + plane * 2) & 0x3FF

    layers = {}
    for li, (layer, base) in enumerate((("A", vdp["plane_a"]), ("B", vdp["plane_b"]))):
        grid = [[None] * SCREEN_W for _ in range(SCREEN_H)]
        for sy in range(SCREEN_H):
            for sx in range(SCREEN_W):
                y, x = sy * 8, sx * 8
                vs = vsram[li] if vdp["vscroll_mode"] == 0 else vsram[(sx // 2) * 2 + li]
                py = ((y + (vs & 0x3FF) + 4) // 8) % ph
                px = ((x - hscroll(y, li) + 4) // 8) % pw
                e = word(vram, base + (py * pw + px) * 2)
                if e:
                    grid[sy][sx] = (e & 0x7FF, (e >> 13) & 3)
        layers[layer] = grid
    grid = [[None] * SCREEN_W for _ in range(SCREEN_H)]
    sat, link = vdp["sprite_table"], 0
    for _ in range(80):
        a = sat + link * 8
        y = (word(vram, a) & 0x3FF) - 128
        sz = vram[(a + 2) & 0xFFFF]
        attr = word(vram, a + 4)
        x = (word(vram, a + 6) & 0x3FF) - 128
        hsz, vsz = ((sz >> 2) & 3) + 1, (sz & 3) + 1
        for cx in range(hsz):
            for cy in range(vsz):
                gx, gy = (x + 4) // 8 + cx, (y + 4) // 8 + cy
                if 0 <= gx < SCREEN_W and 0 <= gy < SCREEN_H and grid[gy][gx] is None:
                    grid[gy][gx] = (((attr & 0x7FF) + cx * vsz + cy) & 0x7FF, (attr >> 13) & 3)
        link = vram[(a + 3) & 0xFFFF] & 0x7F
        if not link:
            break
    layers["S"] = grid

    new = 0
    tiles = cat["tiles"]
    pal64 = ",".join("%03x" % (c & 0xEEE) for c in cram[:64])
    for layer, grid in layers.items():
        scene = {"name": name, "layer": layer, "palette": pal64, "cells": []}
        sid = len(cat.setdefault("scenes", []))
        for sy in range(SCREEN_H):
            for sx in range(SCREEN_W):
                if grid[sy][sx] is None:
                    continue
                ti, line = grid[sy][sx]
                pat = vram[ti * 32:ti * 32 + 32]
                if len(colours(pat)) < 2:
                    continue                         # blank / single colour: nothing to draw
                key = pat.hex()
                t = tiles.get(key)
                if t is None:
                    t = tiles[key] = {"scene": sid, "line": line, "seen": 0, "layer": layer}
                    scene["cells"].append([sx, sy, key, line])
                    new += 1
                t["seen"] += 1
        if scene["cells"]:
            cat["scenes"].append(scene)
    return new


class Client:
    def __init__(self, port, wait=30.0):
        deadline = time.time() + wait
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
                break
            except OSError:
                if time.time() > deadline:
                    sys.exit(f"No debug server on port {port} (tools/textscan.py debug on, then start the game)")
                time.sleep(0.2)
        self.f = self.sock.makefile("rb")
        self.n = 0

    def call(self, cmd, **kw):
        self.n += 1
        kw.update(cmd=cmd, id=self.n)
        self.sock.sendall((json.dumps(kw) + "\n").encode())
        line = self.f.readline()
        if not line:
            raise ConnectionError("game closed")
        return json.loads(line)


def cmd_watch(args):
    cat = load_catalog()
    c = Client(args.port)
    print("Collecting tiles; quit the game or press Ctrl+C to finish.", flush=True)
    samples = 0
    last_save = time.time()
    try:
        while True:
            vdp = c.call("vdp_state", include="vram,cram,vsram")["vdp"]
            new = add_snapshot(cat, vdp, f"watch {time.strftime('%H:%M:%S')}")
            samples += 1
            if new:
                print(f"+{new} tiles ({len(cat['tiles'])} total)", flush=True)
            if time.time() - last_save > 30:
                save_catalog(cat)
                last_save = time.time()
            time.sleep(args.interval)
    except (KeyboardInterrupt, ConnectionError, OSError):
        pass
    save_catalog(cat)
    print(f"{samples} samples, {len(cat['tiles'])} tiles in {CATALOG}")


def cmd_add(args):
    cat = load_catalog()
    for path in args.snapshots:
        d = json.load(open(path))
        new = add_snapshot(cat, d.get("vdp", d), os.path.basename(path))
        print(f"{path}: +{new}")
    save_catalog(cat)
    print(f"{len(cat['tiles'])} tiles in {CATALOG}")


# ---- text tiles (drawn by hdpack.py) -------------------------------------------------------

def text_masks():
    """1bpp masks of every 8x8 piece the text pack covers (both polarities)."""
    masks = set()
    if not os.path.exists(PACK):
        return masks
    d = open(PACK, "rb").read()
    count = struct.unpack("<I", d[8:12])[0]
    pos = 12
    for _ in range(count):
        kind, t = d[pos], d[pos + 1]
        klen = {0: 32, 1: 8, 2: 33}[kind]
        key = d[pos + 4:pos + 4 + klen]
        side = 8 * t
        pos += 4 + klen + (side * side if kind == 0 else side * side // 8)
        if kind == 1:
            masks.add(key)
        elif kind == 2:
            q = key[32]
            masks.add(key[q * 8:q * 8 + 8])
    return masks


def mask_of(pat):
    cs = sorted(colours(pat))
    hi = cs[-1]
    out = bytearray(8)
    for y in range(8):
        for x in range(8):
            b = pat[y * 4 + x // 2]
            if ((b & 15) if x & 1 else (b >> 4)) == hi:
                out[y] |= 0x80 >> x
    return bytes(out)


# ---- sheets ---------------------------------------------------------------------------------

def rgb(c):
    """9-bit Genesis BGR → 8-bit RGB (linear ladder 0, 36, … 252)."""
    return ((c >> 1) & 7) * 36, ((c >> 5) & 7) * 36, ((c >> 9) & 7) * 36


def palette_of(pal):
    """64 colours of a scene; colour 0 of every row transparent."""
    cols = [int(x, 16) for x in pal.split(",")]
    return [rgb(c) + ((0,) if i % 16 == 0 else (255,)) for i, c in enumerate(cols)]


def nib(pat, x, y):
    b = pat[y * 4 + x // 2]
    return (b & 15) if x & 1 else (b >> 4)


def load_index():
    if os.path.exists(INDEX):
        return json.load(open(INDEX))
    return {"sheets": []}


def cmd_export(args):
    cat = load_catalog()
    if not cat["tiles"]:
        sys.exit(f"No tiles collected yet ({CATALOG}); run: tools/hdart.py watch")
    idx = load_index()
    done_scenes = {s["scene"] for s in idx["sheets"]}
    skip = text_masks()
    os.makedirs(SHEETS, exist_ok=True)
    made = 0
    for sid, sc in enumerate(cat.get("scenes", [])):
        if sid in done_scenes:
            continue
        cells = []
        for sx, sy, key, line in sc["cells"]:
            pat = bytes.fromhex(key)
            if len(colours(pat)) == 2 and mask_of(pat) in skip:
                continue                               # text, drawn from typefaces
            cells.append([sx, sy, key, line])
        if not cells:
            continue
        name = f"{len(idx['sheets']):03d}-{sc['layer']}.png"
        rows = [[0] * (SCREEN_W * SIDE) for _ in range(SCREEN_H * SIDE)]
        for sx, sy, key, line in cells:
            pat = bytes.fromhex(key)
            for y in range(SIDE):
                r = rows[sy * SIDE + y]
                for x in range(SIDE):
                    v = nib(pat, x // SCALE, y // SCALE)
                    r[sx * SIDE + x] = line * 16 + v if v else 0
        png.write(os.path.join(SHEETS, name), SCREEN_W * SIDE, SCREEN_H * SIDE, rows, palette_of(sc["palette"]))
        idx["sheets"].append({"file": name, "scene": sid, "source": sc["name"], "palette": sc["palette"],
                              "cells": cells})
        made += 1
        print(f"{name}: {len(cells)} tiles ({sc['name']}, layer {sc['layer']})")
    json.dump(idx, open(INDEX, "w"), indent=0)
    print(f"{made} new sheets in {SHEETS}" if made else "No new tiles to export.")


def sheet_indices(path, pal):
    """Sheet as palette indices (indexed PNG kept; RGB(A) → (row-less) nearest colour, resolved
    per tile row in cmd_import)."""
    w, h, rows, palette = png.read(path)
    return rows, palette is not None


def cmd_import(args):
    idx = load_index()
    entries = {}
    for s in idx["sheets"]:
        path = os.path.join(SHEETS, s["file"])
        if not os.path.exists(path):
            continue
        rows, indexed = sheet_indices(path, s["palette"])
        pl = palette_of(s["palette"])
        for sx, sy, key, line in s["cells"]:
            pat = bytes.fromhex(key)
            tex = bytearray(SIDE * SIDE)
            changed = False
            for y in range(SIDE):
                for x in range(SIDE):
                    px = rows[sy * SIDE + y][sx * SIDE + x]
                    if indexed:
                        v = px & 15
                    elif px[3] < 128:
                        v = 0
                    else:
                        v = min(range(1, 16), key=lambda i: sum((a - b) ** 2 for a, b in zip(px[:3], pl[line * 16 + i][:3])))
                    tex[y * SIDE + x] = v
                    if v != nib(pat, x // SCALE, y // SCALE):
                        changed = True
            if changed:
                entries[pat] = bytes(tex)
    os.makedirs(os.path.dirname(ART_BIN), exist_ok=True)
    with open(ART_BIN, "wb") as f:
        for pat, tex in entries.items():
            f.write(bytes([SCALE]) + pat + tex)
    print(f"{len(entries)} redrawn tiles → {ART_BIN} (now: tools/hdpack.py build)")
    return len(entries)


def cmd_status(args):
    cat = load_catalog()
    idx = load_index()
    exported = sum(len(s["cells"]) for s in idx["sheets"])
    redrawn = len(open(ART_BIN, "rb").read()) // (1 + 32 + SIDE * SIDE) if os.path.exists(ART_BIN) else 0
    print(f"collected {len(cat['tiles'])}, exported {exported} in {len(idx['sheets'])} sheets, "
          f"redrawn {redrawn} (last import)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch")
    w.add_argument("--port", type=int, default=4390)
    w.add_argument("--interval", type=float, default=0.5)
    a = sub.add_parser("add")
    a.add_argument("snapshots", nargs="+")
    sub.add_parser("export")
    sub.add_parser("import")
    sub.add_parser("status")
    args = ap.parse_args()
    {"watch": cmd_watch, "add": cmd_add, "export": cmd_export, "import": cmd_import,
     "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()
