#!/usr/bin/env python3
"""Drive a running game through the debug server (port 4390) with a list of steps.

    tools/drive.py STEP... [--out DIR]
    tools/drive.py --file STEPS.txt [--out DIR]

Start the game in parallel (headless test runs, docs/notes/work-environment.md):

    tools/drive.py --out build/shots <steps> & tools/run.sh --rom tr

The debug server must be on (`tools/textscan.py debug on`, debug.ini, port 4390). Savestates do
not restore this game correctly – every run plays from boot. Check that no other game instance
is running first (`pgrep -fl ADRecomp`): a second instance cannot bind the port and the driver
would talk to the other game.

Steps (frames are V-ints of the game):
    W:n            wait n frames
    BUTTON[:n]     press UP DOWN LEFT RIGHT A B C START (held 6 frames), then wait n (default 30)
    H:BUTTON,n     hold a button for n frames
    S:name         screenshot DIR/name.png (+ name.hd.png when the HD frame is on)
    V:name         VDP state with VRAM/CRAM/VSRAM → DIR/name.json
    R:name         64 KiB RAM $FF0000-$FFFFFF → DIR/name.ram
    Z:name         8 KiB Z80 RAM (sound driver, sound.md) → DIR/name.z80
    ZS             print the Z80 registers and bus state
    WAV:name       record the sound output to DIR/name.wav until WAV:stop
    G:row          scenario list: press DOWN until row `row` (0-9 on screen) is highlighted
    X:x,y          map: move the cursor to hex (x, y) ($FFCD1E + $FFCD20, map.md)
    P:addr=hex     write bytes to memory, e.g. P:FFCC27=01 (weather = rain, graphics.md)
    Q              quit the game

Routes (tr build, docs/notes/work-environment.md "Test routes"):
    scenario 0 map:  W:600 START:120 DOWN:20 DOWN:20 A:200 A:200 A:200 UP:30 A:900 W:100 A:200 W:60
    (Load → scenario list → scenario 0 loaded; UP = "Start"; A skips the turn screen)
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time

BITS = dict(UP=0, DOWN=1, LEFT=2, RIGHT=3, B=4, C=5, A=6, START=7)


class Game:
    def __init__(self, port=4390, wait=30):
        t = time.time()
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port))
                break
            except OSError:
                if time.time() - t > wait:
                    raise
                time.sleep(0.2)
        self.f = self.sock.makefile("r")
        self.id = 0

    def call(self, cmd, **kw):
        self.id += 1
        kw.update(id=self.id, cmd=cmd)
        self.sock.sendall((json.dumps(kw) + "\n").encode())
        while True:
            r = json.loads(self.f.readline())
            if r.get("id") == self.id:
                return r

    def frame(self):
        return self.call("ping").get("frame", 0)

    def wait(self, n):
        f0 = self.frame()
        while self.frame() < f0 + n:
            time.sleep(0.005)

    def press(self, button, hold=6, after=30):
        self.call("set_input", keys="%x" % (1 << BITS[button]))
        self.wait(hold)
        self.call("set_input", keys="0")
        self.wait(after)

    def mem(self, addr, size):
        return bytes.fromhex(self.call("read_memory", addr="0x%06X" % addr, size=size)["hex"])

    def ram(self):
        return b"".join(self.mem(0xFF0000 + o, 4096) for o in range(0, 0x10000, 4096))

    def cursor(self):
        m = self.mem(0xFFCD1E, 4)
        return m[0] + m[2], m[1] + m[3]

    def goto_hex(self, x, y):
        for _ in range(40):
            cx, cy = self.cursor()
            if (cx, cy) == (x, y):
                return True
            b = "RIGHT" if cx < x else "LEFT" if cx > x else "DOWN" if cy < y else "UP"
            self.press(b, hold=4, after=25)
        return False

    def list_row(self, tmp):
        """Highlighted row of the scenario list (white at x 300 of the 1x screenshot)."""
        self.call("screenshot", path=tmp)
        self.wait(2)
        d = subprocess.run(["ffmpeg", "-v", "error", "-i", tmp, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True).stdout
        row = None
        for i in range(8):
            o = ((24 + 24 * i + 4) * 320 + 300) * 3
            if d[o] > 200 and d[o + 1] > 200 and d[o + 2] > 200:
                row = i
        return row


def run(steps, out):
    os.makedirs(out, exist_ok=True)
    g = Game()
    try:
        for step in steps:
            k, _, a = step.partition(":")
            if k == "W":
                g.wait(int(a))
            elif k == "S":
                g.call("screenshot", path=os.path.join(out, a + ".png"))
            elif k == "V":
                json.dump(g.call("vdp_state", include="vram,cram,vsram"), open(os.path.join(out, a + ".json"), "w"))
            elif k == "R":
                open(os.path.join(out, a + ".ram"), "wb").write(g.ram())
            elif k == "Z":
                z = b"".join(bytes.fromhex(g.call("read_z80_ram", addr=o, len=1024)["data"])
                             for o in range(0, 0x2000, 1024))
                open(os.path.join(out, a + ".z80"), "wb").write(z)
            elif k == "ZS":
                r = g.call("z80_state")
                print("z80_state", json.dumps({k2: v for k2, v in r.items() if k2 not in ("ram", "id")})[:400], flush=True)
            elif k == "WAV":
                if a == "stop":
                    g.call("audio_wav", action="stop")
                else:
                    g.call("audio_wav", action="start", path=os.path.join(out, a + ".wav"))
            elif k == "G":
                tmp = os.path.join(out, "_row.png")
                for _ in range(30):
                    if g.list_row(tmp) == int(a):
                        break
                    g.press("DOWN", after=30)
                else:
                    sys.exit("scenario list row not reached")
            elif k == "X":
                x, y = (int(v) for v in a.split(","))
                if not g.goto_hex(x, y):
                    print("cursor stopped at", g.cursor(), flush=True)
            elif k == "H":
                b, n = a.split(",")
                g.call("set_input", keys="%x" % (1 << BITS[b]))
                g.wait(int(n))
                g.call("set_input", keys="0")
                g.wait(30)
            elif k == "P":
                addr, _, data = a.partition("=")
                g.call("write_memory", addr="0x%06X" % int(addr, 16), hex=data)
            elif k == "Q":
                return                   # quit in finally
            elif k in BITS:
                g.press(k, after=int(a) if a else 30)
            else:
                sys.exit(f"unknown step {step!r}")
            print(step, g.frame(), flush=True)
    finally:
        try:
            g.call("quit")
        except (OSError, ValueError):
            pass                         # already gone


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("steps", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--out", default="build/shots")
    args = ap.parse_args()
    steps = args.steps + (open(args.file).read().split() if args.file else [])
    if not steps:
        ap.error("no steps")
    run(steps, args.out)


if __name__ == "__main__":
    main()
