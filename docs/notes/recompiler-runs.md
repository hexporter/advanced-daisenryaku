# Native coverage and the interpreter

How the game's code becomes native functions, what still reaches the tier-3 interpreter, and how
to tell. Tools: `tools/README.md` (fold.sh, dispatch_scan.py).

## Discovery

- No disassembly exists: functions are found heuristically (vector table + BSR/JSR/RTS walk,
  `jump_table_autodiscovery`), from seeds in `recomp/game/game.toml` (`extra`, `late_extra`) and
  from interpreter evidence taken over by `tools/fold.sh` (`ad_floor.discovery.toml`).
- State: 1666 functions in the tr build (15.11.2026). A play session interprets nothing.
- Code layout: the V-int `$00518C` jumps to `$0FA00C`; `$0FA000–$0FFFFF` is a separate program
  (interrupt code, menu entry 8, `vint.md`).

## Evidence files (per build folder, copied to `evidence/<time>/` by `run.sh`)

| File | Meaning |
|---|---|
| `exec_pcs.txt` | every instruction address the interpreter executed – **the measure**: empty = fully native session |
| `floor_coverage.toml` | interpreter entries that **returned** to native code, with their subtree; input of `fold.sh` |
| `floor_unsafe.toml` | entries the interpreter declined (unbalanced stack); the miss was a no-op |
| `dispatch_misses.toml`, `interior_label_misses.toml` | computed targets without a function / inside a function |

"The fold finds nothing" does not mean "nothing interpreted": an interpreter capsule
(`m68k_interp_run_framed`) ends only at a depth-0 `rts` or a game hook. A target that throws the
stack away and jumps on (below) never returns, is not written to `floor_coverage.toml`, and
everything it reaches runs interpreted – for hours, since the guard counts instructions per frame.

## The interpreter stays on

`GENESIS_FLOOR=0` (or `tier3_floor_default = 0` in `ad_spec.c`) switches it off. Not done:
with it off a dispatch miss is not executed at all (silent no-op) and `floor_coverage.toml`
stays empty, while discovery here rests on evidence, not on a disassembly. There is no speed
to gain.

## How code is reached without a static call

`tools/dispatch_scan.py` finds the first two patterns; the others were found from evidence.

1. **Menu tables** – records `ID.w, Text.l, Handler.l` (or two handlers), end `$FFFF`, run by
   `jmp (a0)` / `jsr (a0)` after the list engine (`$00F78E`, `$7D64`; `menu.md`).
2. **Handler pointers** – `move.l #ADDR,0(a0)` (object handlers, called through the object
   loop) and `move.l #ADDR,$FFC54A` / `$FF0042` (state handlers of the `$0FA000` program).
3. **Tables of `bra.w`** reached by an indexed jump. Direction table of the list cursor,
   `$007F00–$007F28`: `lsl.w #2,d7 / lea $7F00(pc),a6 / jsr (a6,d7.w)` at `$007E6A`; d7 = d-pad
   bits (0 left, 1 right, 2 up, 3 down), row in `d1` (`$FFCD38`), column in `d2` (`$FFCD39`),
   every move plays sound `$AD`. Indexes 3 and 7 (left + right) are only possible on a keyboard.
4. **Plain pointer tables**. `$015F0C–$015F8F`, 33 longwords, called by `movea.l 0(a1),a6 /
   jsr (a6)` at `$015EF8`: each target sets up a battle object in `a1` (handler into `0(a1)`,
   sound number `$95–$9D` into `d0`). **Hypothesis:** one entry per weapon or effect type.
5. **Stack-reset jumps** – `movea.l $FFCDA6,a7` followed by a jump: the game drops its call
   chain. Native code would keep its C frames, so a game hook at the jump does a `longjmp` to
   the entry wrapper and restarts at the target (`ad_spec.c`, same mechanism as the soft reset,
   `vint.md`):

   | Site | Target | Where |
   |---|---|---|
   | `$011940` | `$00863E` map loop | Load in the Record menu (`$0118F2`) |
   | `$0118EC` | `$005EAA` title menu | Quit in the Record menu (`$0118E8`) |
   | `$006850` | `$005EAA` | map loader, no army left (not exercised) |

   Other sites of `movea.l $FFCDA6,a7`: `$006340`, `$0088D8` (→ `jmp $0FA000`), `$00B6B4`,
   `$00B6CA`, `$00C6DA`. `$FFCDA6` is stored by `$005EAA` and two other native sites.

**Handlers that pop the stack** are ordinary code: `$011DC6` begins with `movea.l (a1),a0 /
move.l a0,-(a7)` and its yes/no handlers `$011E0A`/`$011E10` begin with `movea.l (a7)+,a0`
(likewise `$010564` with `$01057C`/`$01059A`). They only fail when the function is native and
the handler interpreted: the interpreter is then entered with one longword more on the stack
than a function entry has and declines. With both native the generator's stack accounting
covers it. `$011860` (`movea.l (a7)+,a0 / bra $0117AA`) really drops a return address and
restarts the Record menu.

Seeding a target inside an existing function splits that function; the upper part ends in a
tail call (`RECOMP_TAIL_NATIVE`), e.g. `$01612A` → `$016130`, `$0161B8` → `$0161BE`.

## Seeding rules

- New seeds only with evidence: the body does not jump back above its entry and leaves the
  stack alone (or its stack use is understood, as above).
- Gate for every change of the function set: `tools/compare_native_coverage.py` between a
  probe generation before and after – no native instruction may be lost.
- `fold.sh` denies a folded function automatically when the runner reports an unsafe exit or an
  interior label in it (`ad_floor.deny.toml`, empty at present); nothing is taken over between a
  denied function and the next function start.
- Menu pattern `jsr $7D64 / beq / jmp (a0)` with the handlers in the same function: native in
  `$0086BE`, `$00A8BE`, `$00C334`, `$00CAD2`, `$00F708`, `$012064`, `$012386`, `$012476`.

## Still interpreter (reached by no session so far)

| Target | Why |
|---|---|
| `$0088C2` (table `$0088F8`) | ends in `movea.l $FFCDA6,a7 / jmp $0FA000` |
| `$006304` (table `$00621E`) | the stack reset at `$006340` is followed by more code, not a jump |
| `$0087AC` (table `$0088E2`, `jsr (a0)`) | enters the middle of the map loop `$0086BE` and never returns |
| `$0FAC90` (H-int handler, `rte`), `$0FDEF6` (switches stacks) | interrupt/stack code of the `$0FA000` program |

False positives of `dispatch_scan.py` (data stored with `move.l #…`): `$00E080`, `$00F080`,
`$014000`, `$016772`, `$0167F0`, `$0175BA`.
