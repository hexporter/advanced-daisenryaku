#!/usr/bin/env python3
"""Find Japanese text on the screen of the running game (docs/notes/textscan.md).

Reads the VDP state through the runner's TCP debug server (needs debug.ini next to the binary)
and looks for glyphs of the JP ROM's two fonts in the visible name-table cells:
- 16x16 font $03C86A: a 2x2 cell block whose four tiles are the four quarters of one Japanese
  glyph (kana, kanji, 、。・) – a single tile can match graphics by chance, a whole glyph cannot;
- 8x8 font $03850E: one cell with a Japanese glyph (katakana) next to another 8x8 font cell
  (text run), pattern not shared with a Latin glyph.
A tile matches when it has exactly two colours and one of them, taken as ink, gives the glyph's
bit pattern (blank quarters: one colour). Each distinct text line is reported once, with the frame,
the screen position and a screenshot.

    tools/textscan.py run [--rom tr] [--script FILE] [--frames N] [--no-turbo]
        start the game headless (through tools/run.sh), optionally driven by an input script
        (runner format, docs/notes/work-environment.md), scan until it exits
    tools/textscan.py debug on|off [--rom tr]
        create / remove debug.ini in the build folder (port 4390) for watch
    tools/textscan.py watch [--port 4390]
        attach to a game started with tools/run.sh (after "debug on") and scan while you play;
        stop with Ctrl+C, the report is written then
    tools/textscan.py check SNAPSHOT.json
        scan a saved snapshot (written next to every finding) again, e.g. after changing this tool

Report: build/textscan/<time>/report.md (+ snapshots and screenshots). Exit code 1 if Japanese
text was found. Needs Python >= 3.11, no packages.
"""
import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adtext import FONT_BASE, FONT_GLYPHS, ROOT, load_charmap  # noqa: E402

FONT8_BASE = 0x03850E
FONT8_GLYPHS = 169            # codes $00-$A7 as in the 16x16 font, $A8+ icons (text-map.md)
PORT = 4390
SCREEN_H = 224


def config():
    """KEY=VALUE pairs of config.env (shell syntax, simple values only)."""
    cfg = {}
    path = os.environ.get("CONFIG_ENV", os.path.join(ROOT, "config.env"))
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = os.path.expandvars(v.strip().strip("'\""))
    return cfg


def is_japanese(c):
    o = ord(c)
    return (0x3040 <= o <= 0x30FF          # hiragana, katakana (incl. ー ・)
            or 0x4E00 <= o <= 0x9FFF       # kanji
            or c in "、。々")


class Fonts:
    """Bit patterns (8 bytes, MSB = left pixel) of the JP glyphs of both fonts."""

    def __init__(self, rom, chars):
        self.chars = chars
        latin = set()
        self.quarters = {}            # 16x16: pattern -> [(glyph, quarter)]
        self.glyphs16 = {}            # glyph -> 4 patterns (TL, TR, BL, BR)
        for g in range(FONT_GLYPHS):
            qs = [bytes(rom[FONT_BASE + g * 32 + q * 8:FONT_BASE + g * 32 + q * 8 + 8]) for q in range(4)]
            if is_japanese(chars[g]):
                self.glyphs16[g] = qs
                for q, m in enumerate(qs):
                    if any(m):
                        self.quarters.setdefault(m, []).append((g, q))
            else:
                latin.update(qs)
        self.font8 = {}               # 8x8: pattern -> glyph (Japanese only)
        for g in range(FONT8_GLYPHS):
            m = bytes(rom[FONT8_BASE + g * 8:FONT8_BASE + g * 8 + 8])
            if g < 0xA8 and is_japanese(chars[g]):
                self.font8.setdefault(m, g)
            else:
                latin.add(m)
        self.text8 = set(self.font8) | {m for m in latin if any(m)}   # any 8x8 font cell
        for m in latin:               # a pattern a Latin glyph also has proves nothing
            self.font8.pop(m, None)
        self.text8 -= {bytes(8)}


def tile_masks(vram, t):
    """Ink patterns of tile t: [] if it has more than two colours, [blank] if one."""
    d = vram[t * 32:t * 32 + 32]
    px = []
    for b in d:
        px.append(b >> 4)
        px.append(b & 15)
    cols = set(px)
    if len(cols) == 1:
        return [bytes(8)]
    if len(cols) > 2:
        return []
    out = []
    for c in cols:
        out.append(bytes(sum(0x80 >> x for x in range(8) if px[y * 8 + x] == c) for y in range(8)))
    return out


def classify_tiles(vram, fonts):
    """Per VRAM tile: 16x16 JP quarters {(glyph, quarter)}, blank tiles, 8x8 JP glyph, 8x8 font cells."""
    q16, blank, j8, t8 = {}, set(), {}, set()
    for t in range(0x800):
        for m in tile_masks(vram, t):
            if m == bytes(8):
                blank.add(t)
                continue
            if m in fonts.quarters:
                q16.setdefault(t, set()).update(fonts.quarters[m])
            if m in fonts.font8:
                j8[t] = fonts.font8[m]
            if m in fonts.text8:
                t8.add(t)
    return q16, blank, j8, t8


def planes(vdp, vram):
    """Planes A and B: (name, base, width, height, function cell -> screen (x, y) or None)."""
    w = 1 << vdp["plane_w_shift"]
    h = vdp["plane_h_mask"] + 1
    hs_base, hs_mode = vdp["hscroll"], vdp["hscroll_mask"]
    width_px = 320 if vdp["h40"] else 256
    vsram = vdp["vsram"]

    def hscroll(line, plane):
        if hs_mode == 0:
            line = 0
        elif hs_mode == 2:
            line &= ~7
        a = hs_base + line * 4 + plane * 2
        return -((vram[a] << 8 | vram[a + 1]) & 0x3FF)     # scroll value moves the plane right

    out = []
    for name, base, idx in (("A", vdp["plane_a"], 0), ("B", vdp["plane_b"], 1)):
        vs = vsram[idx] & 0x3FF if vdp["vscroll_mode"] == 0 else None

        def pos(cx, cy, idx=idx, vs=vs):
            v = vs if vs is not None else vsram[(cx // 2) * 2 + idx] & 0x3FF
            y = (cy * 8 - v) % (h * 8)
            if y > SCREEN_H - 8:
                return None
            x = (cx * 8 - hscroll(y, idx)) % (w * 8)
            if x > width_px - 8:
                return None
            return x, y
        out.append((name, base, w, h, pos))
    # No window plane: the game switches it off at init ($00502E: $9100 $9200) and never writes
    # registers $11/$12 again; the window table address then points into tile data (textscan.md).
    return out


def scan(snap, fonts):
    """Japanese glyphs on screen: sorted list of (plane, x, y, char, font size)."""
    vdp = snap["vdp"]
    # Nothing is visible with the display off or a single-colour palette (fade): the game loads
    # tiles in such frames, and the name tables then hold leftovers or font sheets (textscan.md).
    if not vdp["display"] or len(set(vdp.get("cram", [0, 1]))) == 1:
        return []
    vram = bytes.fromhex(vdp["vram"])
    q16, blank, j8, t8 = classify_tiles(vram, fonts)
    found = set()
    for name, base, w, h, pos in planes(vdp, vram):
        def tile(cx, cy):
            a = base + ((cy % h) * w + (cx % w)) * 2
            return (vram[a] << 8 | vram[a + 1]) & 0x7FF

        def glyph_at(cx, cy, g):
            for q, m in enumerate(fonts.glyphs16[g]):
                t = tile(cx + q % 2, cy + q // 2)
                if (t not in blank) if not any(m) else ((g, q) not in q16.get(t, ())):
                    return False
            return True

        for cy in range(h):
            for cx in range(w):
                t = tile(cx, cy)
                # 16x16: anchor the glyph from any of its non-blank quarters, check all four
                for g, q in q16.get(t, ()):
                    ax, ay = cx - q % 2, cy - q // 2
                    p = pos(ax % w, ay % h)
                    if p and glyph_at(ax, ay, g):
                        found.add((name, p[0], p[1], fonts.chars[g], 16))
                # 8x8: JP glyph inside a run of font cells
                if t in j8 and (tile(cx - 1, cy) in t8 or tile(cx + 1, cy) in t8):
                    p = pos(cx, cy)
                    if p:
                        found.add((name, p[0], p[1], fonts.chars[j8[t]], 8))
    return sorted(found, key=lambda f: (f[0], f[2], f[1]))


def lines(found):
    """Group glyphs into text lines: (plane, y, x of the first glyph, text)."""
    rows = {}
    for plane, x, y, c, size in found:
        rows.setdefault((plane, y, size), []).append((x, c, size))
    out = []
    for (plane, y, size), gs in sorted(rows.items()):
        gs.sort()
        text, start, last = "", gs[0][0], None
        for x, c, _ in gs:
            if last is not None and x - last > size * 2:     # a gap of more than one glyph
                out.append((plane, y, start, text))
                text, start = "", x
            elif last is not None and x - last > size:
                text += " "
            text += c
            last = x
        out.append((plane, y, start, text))
    return out


class Client:
    """Line-delimited JSON over TCP (runner cmd_server.c)."""

    def __init__(self, port, wait=30.0):
        deadline = time.time() + wait
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
                break
            except OSError:
                if time.time() > deadline:
                    raise SystemExit(f"No debug server on port {port} (debug.ini next to the binary?)")
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

    def snapshot(self):
        frame = self.call("ping").get("frame", 0)
        return {"frame": frame, "vdp": self.call("vdp_state", include="vram,cram,vsram")["vdp"]}


class Report:
    """Distinct text lines with first frame, count, screenshot and snapshot."""

    def __init__(self, out, title):
        self.out, self.title = out, title
        os.makedirs(out, exist_ok=True)
        self.seen = {}       # (plane, y, x, text) -> [first frame, samples, file stem]
        self.samples = 0

    def add(self, snap, found, client=None):
        self.samples += 1
        new = []
        for key in lines(found):
            plane, y, _, text = key
            # the same line again, part of it (typewriter, scrolling) or a longer version of it
            same = [k for k in self.seen if k[0] == plane and k[1] == y and (text in k[3] or k[3] in text)]
            longer = [k for k in same if len(k[3]) < len(text)]
            if same and not longer:
                self.seen[same[0]][1] += 1
                continue
            first, n = snap["frame"], 1
            for k in longer:
                f, c, _ = self.seen.pop(k)
                first, n = min(first, f), n + c
            self.seen[key] = [first, n, None]
            new.append(key)
        if new:
            stem = f"f{snap['frame']:07d}"
            if client:
                client.call("screenshot", path=os.path.join(self.out, stem + ".png"))
            with open(os.path.join(self.out, stem + ".json"), "w") as f:
                json.dump(snap, f)
            for key in new:
                self.seen[key][2] = stem
                plane, y, x, text = key
                print(f"frame {snap['frame']}: {text}  (plane {plane}, x={x} y={y})", flush=True)

    def write(self):
        path = os.path.join(self.out, "report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Text scan {self.title}\n\n{self.samples} samples, "
                    f"{len(self.seen)} lines with Japanese glyphs.\n\n")
            if self.seen:
                f.write("| First frame | Text | Plane | x | y | Samples | Screenshot |\n"
                        "|---|---|---|---|---|---|---|\n")
                for (plane, y, x, text), (frame, n, stem) in sorted(self.seen.items(), key=lambda i: i[1][0]):
                    shot = f"[{stem}.png]({stem}.png)" if os.path.exists(os.path.join(self.out, stem + ".png")) else stem
                    f.write(f"| {frame} | {text} | {plane} | {x} | {y} | {n} | {shot} |\n")
        print(f"{self.samples} samples, {len(self.seen)} lines with Japanese glyphs. Report: {path}")
        return 1 if self.seen else 0


def sample(client, fonts, report, interval):
    while True:
        try:
            snap = client.snapshot()
        except (ConnectionError, OSError, json.JSONDecodeError):
            return
        report.add(snap, scan(snap, fonts), client)
        time.sleep(interval)


def build_dir(variant):
    return os.path.join(ROOT, "build", f"recomp-{variant}")


def set_debug(variant, on, port=PORT):
    """Create or remove debug.ini; returns True if it existed before."""
    path = os.path.join(build_dir(variant), "debug.ini")
    existed = os.path.exists(path)
    if on and not existed:
        with open(path, "w") as f:
            f.write(f"port={port}\n")
    elif not on and existed:
        os.remove(path)
    return existed


def report_dir():
    return os.path.join(ROOT, "build", "textscan", time.strftime("%Y%m%d-%H%M%S"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--rom", default="tr", choices=["jp", "en", "tr"])
    r.add_argument("--script", help="input script (runner format)")
    r.add_argument("--frames", type=int, help="quit after N frames")
    r.add_argument("--no-turbo", action="store_true", help="run at normal speed")
    r.add_argument("--interval", type=float, default=0.0, help="seconds between samples")
    d = sub.add_parser("debug")
    d.add_argument("state", choices=["on", "off"])
    d.add_argument("--rom", default="tr", choices=["jp", "en", "tr"])
    w = sub.add_parser("watch")
    w.add_argument("--port", type=int, default=PORT)
    w.add_argument("--interval", type=float, default=0.25, help="seconds between samples")
    c = sub.add_parser("check")
    c.add_argument("snapshot", nargs="+")
    args = ap.parse_args()

    if args.cmd == "debug":
        set_debug(args.rom, args.state == "on")
        print(f"debug.ini {args.state} in {build_dir(args.rom)}"
              + (f" (port {PORT}); start the game with tools/run.sh --rom {args.rom}" if args.state == "on" else ""))
        return 0

    rom = open(config()["ROM_JP_PATH"], "rb").read()
    fonts = Fonts(rom, load_charmap())

    if args.cmd == "check":
        report = Report(report_dir(), "check")
        for p in args.snapshot:
            with open(p) as f:
                snap = json.load(f)
            report.add(snap, scan(snap, fonts))
        return report.write()

    if args.cmd == "watch":
        client = Client(args.port)
        report = Report(report_dir(), f"watch, port {args.port}")
        print("Scanning; quit the game or press Ctrl+C to finish.", flush=True)
        try:
            sample(client, fonts, report, args.interval)
        except KeyboardInterrupt:
            pass
        return report.write()

    # run: the game through tools/run.sh (evidence as usual), debug.ini only for this run
    existed = set_debug(args.rom, True)
    runner = []
    if not args.no_turbo:
        runner.append("--turbo")
    if args.frames:
        runner += ["--max-frames", str(args.frames)]
    if args.script:
        runner += ["--input-script", os.path.abspath(args.script)]
    env = dict(os.environ, GENESIS_NO_LAUNCHER="1")
    out = report_dir()
    report = Report(out, f"run --rom {args.rom}" + (f" --script {args.script}" if args.script else ""))
    os.makedirs(out, exist_ok=True)
    # A scripted run may change settings or saves: keep the save games as they were
    saves = glob.glob(os.path.join(build_dir(args.rom), "*.srm"))
    for p in saves:
        shutil.copy2(p, os.path.join(out, os.path.basename(p)))
    with open(os.path.join(out, "run.log"), "w") as log:
        game = subprocess.Popen([os.path.join(ROOT, "tools", "run.sh"), "--rom", args.rom] + runner,
                                env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            client = Client(PORT)
            if not existed:
                set_debug(args.rom, False)     # read at startup; remove it right away
            sample(client, fonts, report, args.interval)
        finally:
            if not existed:
                set_debug(args.rom, False)
            game.wait()
            for p in saves:
                shutil.copy2(os.path.join(out, os.path.basename(p)), p)
    return report.write()


if __name__ == "__main__":
    sys.exit(main())
