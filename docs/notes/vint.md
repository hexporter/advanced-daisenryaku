# V-int, wait loop, soft reset

Evidence: disassembly of the JP ROM.

## V-int `$00518C`

```
$00518C  move.w #$2700,sr ; movem.l d0-d7/a0-a6,-(a7)
$005194  tst.w $FF0040 ; beq $51A2 ; else jmp $0FA00C    (alternative handler)
$0051A2  addq.b #1,$FF0122                                (frame counter)
$0051A8  tst.b $FFCDA0 ; beq $5218
$0051B6  cmpi.b #6,$FF0110 ; beq $5208                    (mode 6: no DMA)
$0051C0  … VDP DMA …
$005208  d0 = $FF0110 × 6 ; jsr $523E(pc,d0.l)            (mode table)
$005218  clr.b $FF0120                                    (clear wait flag)
$00521E  bsr $50F0 ; bsr $5AF4 ; count down $FF0150
$005234  movem.l (a7)+,… ; move.w #$2300,sr ; rtr         (ends with RTR, not RTE)
```

- `$FF0110` = V-int mode, `$FF0120` = wait flag, `$FF0122` = frame counter.
- Mode table `$00523E`, 7 entries of 6 bytes (`jmp abs.l`), followed by `rts` at `$005268`:
  0→`$526A` 1→`$54F0` 2→`$5714` 3→`$5716` 4→`$5876` 5→`$5602` 6→`$2CB2`.
  The recompiler does not find the entries by itself; they are seeded in `game.toml`.
- Mode 4 = battle animation, mode 2 between battle and map (black screen), mode 5 while the map is
  drawn (`phases.md`).
- The game hook at `$0051A2` (frame counter) runs every frame: RAM recording and automatic
  fast-forward (`ad_spec.c`, `phases.md`).

## WaitForVBlank `$005AC6`

```
$005AC6  move.w #$2300,sr
$005ACA  move.b #1,$FF0120
$005AD2  tst.b $FF0120 ; bne.b $5AD2
$005ADA  rts
```
5 instead of 4 instructions → the generator's yield pattern does not match. The runner still
yields via `glue_yield_for_interrupt_poll()` at the return – but **not inside the V-int**.

## Soft reset `$000382` out of the V-int

Mode 6 handler `$002CB2`:
```
$002CB2  tst.b $FF0100 ; beq $2CC6
$002CBA  btst #7,$FF0141
$002CC2  bne.w $000382           ; jumps out of the interrupt
```
`$000382`: `move.w #$2700,sr`, display off, `lea $FF00.w,a7` (new stack), `clr.b $FF0100`,
re-initialisation → main loop. Never returns from the V-int.

- `$FF0140/$FF0142` are initialised with `$FF00` at `$005AE2`. **Hypothesis:** joypad state of
  player 1/2, bit 7 of `$FF0141` = START.
- Run natively inside the V-int this never yields: the main program would run in the V-int
  context (watchdog "bus accesses without yield" in the wait loop). Pairing a joypad is enough
  to set the bit.

### Solution (`recomp/game/ad_spec.c`, hooks in `game.toml`)

1. Hook `$002CC2`: with Z=0, mark the reset as pending, return 1 → handler ends (implicit RTS),
   V-int as normal.
2. Hook `$005AC6`: reset pending → `longjmp` to the entry wrapper, reset the tail-frame chain,
   `recomp_call_addr($000382)`.
Risk (**Hypothesis**, untested): if interpreted code calls `$005AC6`, the interpreter's floor flag
stays set during the `longjmp` → later misses would no longer be interpreted.


`$000382` and the seven mode-table entries must be functions (`[functions].extra`): otherwise
`recomp_call_addr` ends in an interpreter capsule that holds the whole main program, and while a
capsule runs the interpreter does not re-enter, so interpreted V-int handlers stop working
(black screen, hang).

The same entry-wrapper mechanism restarts the game after stack-reset jumps (Load, Quit;
`recompiler-runs.md`).
