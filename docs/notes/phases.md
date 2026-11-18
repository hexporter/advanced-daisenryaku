# Game phases in RAM

Which RAM bytes tell whose turn it is and whether a battle is running – the basis of the
automatic fast-forward (`controls.md`). Evidence: three RAM recordings with hand-marked phases
(two enemy turns; three enemy turns with 9 battles; standard map Ural with 3–4 enemies and
19 battles), analysed with `tools/ramphase.py`.

## Findings

| RAM | Meaning |
|---|---|
| `$FFCDD2` | `$01` while the computer is moving, otherwise `$00`. Switches at the player's end of turn and back only after the last computer opponent. 99.4 % over all recordings; the deviations are the hand-marked boundaries |
| `$FFCD04` | `$66` (briefly `$46`) during every battle, in no other phase; stays `$66` for ~56 V-ints after the animation. Other values `00 80 A0 A1 C0 E0 E1` (`$A0` during the enemy turn and on the settings menu and scenario list, `$80` on the turn screen, `$E0` own turn; **Hypothesis:** screen/sequence state) |
| `$FF0110` (V-int mode, `vint.md`) | 4 during the battle animation; before a battle `5 → 2 → 4`, after it `4 → 2` (black screen), then 5 while the map is drawn |
| `$FFB10C` | not usable: bit 6 looked like "computer's turn" on the first maps but the byte stays `$0A` for a whole game on Ural |

The lead-in before a battle (attacker moving, black screen) cannot be told from "thinking";
it is fast-forwarded too. Other bytes with high hit rates (`$FF40xx`, `$FF9E7x/$FF9F2x`) look
like display buffers.

## Rule of the automatic fast-forward (`ad_spec.c`, hook `$0051A2`, every frame)

Fast-forward while `$FFCDD2` = 1 and not (`$FFCD04` ∈ {`$46`, `$66`} and `$FF0110` = 4), and
the system menu is not open (`saving.md`). On after the state has been stable for 8 V-ints, off
immediately. Checked offline on all recordings: never during a battle animation.

## Tool: RAM recording with phase marking

1. `tools/run.sh --ramlog` → the recorder in `ad_spec.c` writes
   `build/recomp-<variant>/evidence/<time>/ramlog.bin`: one record with the changed bytes
   every 8 frames (`AD_RAMLOG_EVERY`) and on every phase change (format: comment in `ad_spec.c`).
2. While playing, set the phase with a number key in the game window:

   | Key | Phase |
   |---|---|
   | `0` | other (menus, intro) – initial value |
   | `1` | own turn |
   | `2` | enemy turn |
   | `3` | battle on/off (toggles; back to the previous phase) |

   Changes are logged as `[ADS] Phase …`. Imprecise timing is harmless: the analysis ignores
   1 s after each change.
3. Analysis: `tools/ramphase.py <ramlog.bin> …` (`tools/README.md`).

The hook sits at `$0051A2` (`addq.b #1,$FF0122` in the V-int) because it runs every frame,
even while the main program computes for a long time; the runner does not call
`on_frame_pre/post` of `GameSpec`.
