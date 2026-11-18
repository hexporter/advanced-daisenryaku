# Camouflage frame in the 16:9 margins

Outside the zoomed map the picture is 320 px wide and sits in the middle of the 16:9 frame
(`map.md`, "16:9"). `recomp/game/ad_frame.c` paints the two side margins: the cream double
line of the game's panels and a plate in the camouflage of the country in play. It draws
everything itself (value noise, no ROM tiles, no art files) and writes ARGB pixels through
the hook of framework patch 0011 (`recompiler.md`). Presentation only – nothing the game
reads changes. `AD_FRAME=0` turns it off.

## Armies and countries (RAM)

| Address | Meaning | Evidence |
|---|---|---|
| `$FFCC17` | army in play, 0–7 | RAM recordings (`build/recomp-en/evidence/*/ramlog.bin`): changes with every turn screen |
| `$FFCC10` (long) | pointer to that army's record; 0 until a scenario is loaded (intro, title menu, settings menu, scenario list), `$FFFFC800` on the first turn screen | RAM dumps per screen, scenario 0 |
| `$FFC800` + n·`$20` | army record n (8 records): name (8 characters) at +`$10`; `$FF` at +`$0F` = unused | dumps; scenario 0 uses armies 0 and 6 |
| unit record +`$0F` (`map.md`) | army number 0–7; palette line = army >> 1 (B1/B2, R1/R2, G1/G2, Y1/Y2) | dumps; scenario 0's enemy = 6, palette 3 |

- Routine `$008C1A` advances `$FFCC17` and `$FFCC10` to the next army.
- The settings menu and the scenario list already hold army records (army 0 named after the
  first scenario's side) and `$FFCD04` = `$A0`; only `$FFCC10` tells that nothing is loaded.
- ROM army name table `$0233F0`: 82 entries of 9 bytes (length, 8 characters) – nations, army
  groups, fronts, commanders. The names in RAM follow the language in use, as the table does
  (`translation-rom.md`), so a record's name is looked up in the table and the index gives the
  country (`s_army_nation` in `ad_frame.c`).

## Battles (RAM)

| Address | Meaning |
|---|---|
| `$FFD060` | attacker's record: +`$08` pointer to its unit record, +`$10` pointer to the side's first object |
| `$FFD080` | defender's record, same layout |
| `$FFD100…`, `$FFD380…` | the two sides' objects, `$40` bytes each: +`$10` screen X + 128 (16.16), +`$14` Y |

- In 58 recorded battles the attacker's army was always `$FFCC17`.
- `$FFD060` is the unit that acts (`$FFCD0C`), `$FFD080` its target (`$FFCD42`); the battle
  setup `$00D88A` gives them the object blocks `$FFD100` / `$FFD380`.
- Where the sides stand is read once, on the first battle frame, from the mean start x of each
  block's objects (used = any byte non-zero): in all 48 battles of the RAM recordings the
  attacker's started right (x 245–406), the defender's left (below 0). A block without objects
  is placed by the other's position. **Hypothesis:** a ranged artillery attack shows only its
  target, standing on the right – there a fixed "attacker right" swapped the countries
  (seen in play, not recorded). The choice is logged (`[ADS] Battle: …`).
- Object X is no measure of the side during a battle: it is negative (wraps as a word) while
  an object is off screen, and aircraft fly across to the other side.
- While a battle runs, `$FFCD04` and `$FF0110` leave their battle values for single frames
  (the text routine borrows `$FFCD04`, `text.md`; seen when the panel changes TERRAIN to EXP).
- The battle screen appears at full brightness: 12 V-ints after the confirming press the
  picture is complete, no palette fade.

## What the frame shows

| Screen | Test | Margins |
|---|---|---|
| intro | `$FFCC10` = 0 and `$FF0110` = 6, before the first menu | black |
| campaign briefing, result texts | `$FFCC10` = 0 and `$FF0110` = 6 after a menu was seen | country of army 0 (the player's) |
| title menu, settings menu, scenario list | `$FFCC10` = 0 | plain olive plate |
| turn screen, menus, the game's own map | otherwise | country of army `$FFCC17`, full height |
| zoomed map | `ad_mapzoom_active()` | the map fills lines 8–167; the plate only beside the status bar (lines 168–223) |
| battle | `$FFCD04` ∈ {`$46`, `$66`} and `$FF0110` = 4; read once per battle and kept until 12 frames pass without it (black screen by then) | each margin the country of the side standing there (above); the panel's cream line continues at line 182 |

- During the enemy's turn `$FFCC17` is the enemy's army, so the frame shows the enemy's country.
- **Brightness:** the plate is scaled by the brightest colour component in CRAM and is black
  while the display is off, so it goes dark with the screen (seen: the black frames between
  turn screen and map). **Hypothesis:** a palette fade dims the plate in step; no fading
  transition has been captured with the frame on.
- **Patterns:** Germany (splinter), Poland, Britain, France, USSR, USA, Italy, Finland; every
  other army gets the plain olive plate. Two armies of one country look alike.
- The plate is made at 4x for the margin width in use and sampled for other HD scales; margins
  narrower than 10 screen px stay black.
