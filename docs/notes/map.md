# Hex map: RAM layout and drawing

How the game stores and draws the hex map, and how the zoomed-out HD map is built from it.
Evidence: disassembly of the JP ROM, RAM and VDP dumps of the tr build (scenario 0 "Case Wht",
scenario 9 "Maginot"), Python models of the routines compared with the dumps.

## Terrain

- **`$FFA000`: 64x64 bytes, one per hex, index `Y*64 + X`.** Bit 7 set = off the map / not
  enterable (`$81`, `$A2` around the map); low 7 bits = terrain code.
  Evidence: `$019B26` (terrain at d1 = X, d2 = Y) reads `$FFA000 + Y*64 + X`; the status bar calls
  it (`$009CAE`) and prints the name from `$02AE76`. Checked against the status bar: scenario 0
  (24,31) = `$1A` "Cap.", (26,31) = `$02` "Forest", (27,34) = `$01` "Plain", (25,37) = `$03` "Road".
- Terrain properties: `$02AB3A`, 12 bytes per code (code < `$45`), 6 byte pairs selected by
  `$FFCDAB` (**Hypothesis:** season/weather); pair = (graphic/name index, …). `$019B26` returns the
  name index in d0.
- Map sizes: scenario 0 = X 23–38, Y 25–38 (16x14 hexes); scenario 9 Maginot = X 7–56, Y 7–56
  (50x50 hexes, 2,500 hexes).
- `$FF6000` (movement cost per hex, from `$FFA000` and table `$0238FA`) and `$FF5000`
  (reachability) are rebuilt from it at `$0198F6` / `$019962`.

## View and cursor

| Address | Meaning | Evidence |
|---|---|---|
| `$FFCD1E` / `$FFCD1F` | cursor X / Y relative to the view (hexes) | `$009CD8` places the cursor sprite from them; changes with the cursor |
| `$FFCD20` / `$FFCD21` | view origin X / Y (hexes); map X = `$CD1E + $CD20` | `$00A192`; 23 → 27 when scrolled right (scenario 0) |
| `$FFCD22` / `$FFCD24` (words) | scroll in tiles (3 per hex column, 2 per hex row) | 21 → 33 for origin 23 → 27 |

Cursor sprite: see "Overlays" below.

## How the map is drawn (VDP)

- **Plane B = terrain, plane A = hex grid lines and units** (units are plane tiles, the cursor is a
  sprite). Both name tables at `$E000`; A uses rows 0–31, B rows 32–63 (VSRAM[1] = 256).
- **One hex = a 3x2-tile block (24x16 px)**, laid out like bricks; the hex stagger comes from the
  horizontal scroll per tile row (scroll table `$DC00`, per-cell mode): rows alternate by 12 px
  (e.g. −530 / −542). The pointed hex tops reach into the neighbouring rows' blocks.
- **Fog of war = priority bit per tile:** fogged hexes use tiles without priority on both planes;
  in shadow/highlight mode the VDP darkens them.
- The planes are built in RAM (`$FF8000` = plane A, `$FF9000` = plane B, cleared at `$00A138`) and
  copied to VRAM.
- **The tile block of a hex depends on its neighbours** (pointed tops, road joins): scenario 0,
  plains alone have 20 different blocks; keyed by terrain + the six neighbours + row parity, 3 of
  134 keys stay ambiguous. Fixed tile set (plane B words `$3C8–$3FF`, `$510+` …), not tiles
  composed at runtime.
- Planes are 64 tiles wide = 21 hexes, 32 rows = 16 hex rows. **Small maps fit completely**
  (scenario 0: whole map in the planes, scrolling only changes the scroll values). **Big maps are
  redrawn around the view** (Maginot: plane B changes when the view moves vertically).
- Checked: the full planes of scenario 0 rendered offline with the row stagger and fog give the same
  picture as the game's screen (except the cursor sprite).

## The hex drawer `$012EDA`

Called once per hex by
the full view redraw `$012DC0` (10 rows x 14 columns: X from `$CD20`−1, Y from `$CD21`) and by the
row/column redraws while scrolling (`$012E14`, `$012E44`, `$012E78`, `$012EA8`). Input: a3 →
terrain byte in `$FFA000`, a0 → same index in `$FF7000` (per-hex flags), d1 = row parity.

1. **Terrain graphic:** `g = table[$CDAB][code]`, tables via the pointer list `$013214` (6 entries,
   one per `$CDAB` value; byte per terrain code).
2. **Plain terrain** (g bit 7 clear): block = 6 words at `$038332 + 12·g`.
3. **Joining terrain** (g bit 7 set – e.g. `$03` Road, `$02` Forest): block =
   `$04342A + $300·(g & $7F) + 12·n`, n = 6-bit neighbour mask. Each terrain code has a 32-bit
   class mask at `$0130FC + 4·code` (bits 16–23 replaced by bits 24–31); for each of the six
   neighbours in table order, shift n left and set bit 0 if `mask(this) & mask(neighbour) == 0`
   (neighbour does not join). Neighbour offsets (in `$FFA000` bytes): odd Y `$0130D8` = +65, +64,
   −1, −64, −63, +1; even Y `$0130E4` = +64, +63, −1, −65, −64, +1.
4. **Plane B words** (the 6 block words incl. palette/priority/flip as stored) go to
   `$FF9000 + (Y mod 12)·$100 + (X·6 mod $80)`: words 0–2 = top tile row, 3–5 = bottom row.
5. **Plane A** (same offset in `$FF8000`): priority `$8000` if `$FF7000` bit 6 is set (= hex
   visible, fog otherwise), plus the hex grid tiles `$3C8–$3CD` (top row `$3C8 $3CA $3CC`, bottom
   `$3C9 $3CB $3CD`); `$CC25` ≠ 0 → tile 0 (grid off). Class-mask bit 31 terrains get an
   overlay instead (`$25BF`/`$25E3` + 6·side of the first joining neighbour of three, +`$12` with
   bit 28).

Checked with a Python model of the routine against RAM dumps (tr): plane B identical for all 140
hexes of the view in 3 of 5 dumps (scenario 0 at two scroll positions, Maginot at (45,47)); in the
other two (Maginot at (45,15), same moment) 138 of 140 – the two road hexes next to (47,22), a
"Dmg Road" (`$2C`), were drawn as if it were still a road: the game redraws a changed hex but not
its neighbours. With the wrong parity table 88–116 of 140 match, so the parity rule is real.
Plane A matches except the unit hexes (below). `$01` Plain itself is one fixed block (`$3CE–$3D3`); the many
neighbour-dependent blocks come from the joining codes (road joins, forest edges).

## Units on the map

Evidence: disassembly of `$012D4A`, `$01293E`, `$012B3A`; a Python model of `$012B3A` composed the
6 tiles of every unit on screen and compared them with the VRAM dumps (tr): **33 of 33 identical**
(7 units in scenario 0, 26 in Maginot).

**Unit records: `$FFB000`, 256 × `$18` bytes** (unit number = `$E300` entry & `$7FFF`):

| Byte | Meaning | Evidence |
|---|---|---|
| `$00` | Y; `$FF` = empty slot | `$012D4A`; record 2 = (25,30), the unit seen there |
| `$01` | X | same |
| `$02` (word) | unit type, index into the type table `$02B1F2` (`$22` bytes per type; `+$14` = graphic number) | `$012B3A` |
| `$04` | bit 7 = draws an "E" mark (**Hypothesis:** unit has finished its turn), bit 5 = draws a small square top left, bit 4 = not drawn; low nibble `$A` on all fresh units (**Hypothesis:** strength 10) | `$012B3A`, `$012D4A`, rendered variants |
| `$05`–`$07` | differ by type (`$28`–`$3C`, `$03`–`$0C`, `$00`–`$04`) (**Hypothesis:** fuel, ammo, …) | dumps only |
| `$0F` | army number 0–7 (`frame.md`); palette line = byte >> 1 | `$012B3A`; enemy in scenario 0 = 6, palette 3 |
| `$10` | bit 7 = not drawn (enemy not spotted under fog; also set on empty slots) | `$012D4A`; 5 hidden enemies in scenario 0 |

**Per-view table `$FFE300`:** 12 × 10 words (index ry·12 + rx, relative to `$CD20`/`$CD21`),
`$8000 | unit number` or 0. Rebuilt by `$012D4A` from all 256 records (skips: outside the view,
byte 4 bit 4, byte `$10` bit 7, and while `$CD48` = 2 the unit `$CD0C` – the one being moved).

**Drawing a unit (`$012B3A`):**

1. Tile number `t = $0E2 + 6·(X mod 12) + $48·(Y mod 10)` plus palette `(byte $0F >> 1) << 13`:
   every map position has its own 6 tiles in VRAM, so units are composed per position.
2. The 6 tiles (column-major: TL, BL, TM, BM, TR, BR) are written to VRAM: graphic tile numbers
   from `$05B42A + 12·graphic` (6 words), 4bpp pattern data at `$04852A + 32·number`, each long
   `AND mask | overlay` with mask `$039F5E + $C0·v` and overlay `$039A1E + $C0·v`. v = (byte 4
   bit 7 ? 1 : 0) + (bit 5 ? 2 : 0); with the hex grid off (`$CC25` ≠ 0) v + 3, or the plain
   graphic when v = 0. The masks bake the **hex grid lines** and the marks into the unit tiles.
3. Plane A at the hex (as in `$012EDA`) gets `t … t+5`, keeping the fog priority bit.
4. **On terrain with a plane A overlay** (class-mask bit 31: `$2C $2D $31 $32 $39–$3E`, flag table
   `$012AF4`) the unit becomes a **sprite** instead: object from the free list `$CD9C`,
   x = 24·(X − `$CD20`) + `$8A` (+12 on odd Y), y = 16·(Y − `$CD21`) + `$88`, priority when the hex
   is visible.

Refreshes while scrolling: `$01296C`, `$01299C`, `$0129CA`, `$0129FE` (one view row/column each).
`$FFD100` is a list of 60 × `$40`-byte objects run by `$01405A` each frame.

## Overlays (movement range, attack targets, cursor)

- **Movement range = the fog flags.** On Move the game rewrites `$FF7000` for the whole map:
  `$41` = reachable, 0 = not (`$4D`, `$C1`, `$C0` also seen, next to the enemy; meaning unknown); `$FF5000` then holds the
  remaining move points (0 at the unit, `$FF` = unreachable). The hex drawer `$012EDA` draws it
  like fog: bit 6 set → plane A priority → bright, else darkened by shadow mode. On cancel the
  previous fog flags come back. Checked: the plane B words
  and the priority of all 140 view hexes follow `$012EDA` from the current `$FF7000` in 5 captures
  (plain map, range shown, cursor moved, tank range, attack target).
- **Attack targets:** no map marking. The target cursor jumps to the enemy hex
  (`$CD1E` changes) and an info window (sprites: NAME / X / Y / POW / N) opens at the top.
- **Cursor:** one 32x32 sprite (4x4, tile `$8001`), object `$FFD1C0` in the object list
  (`$FFD100`, run by `$01405A`), placed by `$009CD8`:
  x = 24·cx + `$82` (+12 when cy is even) − 8·`$CD14`, y = 16·cy + `$80` − 8·`$CD16` (VDP sprite
  coordinates, screen + 128), cx/cy = `$CD1E`/`$CD1F`. The view origin row `$CD21` was odd in all
  captures, so "cy even" = odd map Y (same rule as the unit sprites and the plane rows).
- **The unit being moved** is taken out of `$FFE300` (`$012D4A`, `$CD48` = 2, `$CD0C` = its
  record) and shown as a 3x2 sprite (tile `$8094`) at x = 24·(X − `$CD20`) + `$8A` (+12 on odd Y),
  y = 16·(Y − `$CD21`) + `$88` – the same placement as units on overlay terrain (`$012B3A`).
- The two 4x4 sprite columns at screen x 0 and 304 (tiles `$8011`/`$8811`, priority) are black
  masks for the left and right edges of the map.

- **Effects in a hex** are 3x2 sprites with other tiles: the puff of a ranged shot that
  misses is tile `$8021` at the target hex (cursor sprite + (8, 8)).

## Offline renderer (`tools/mapzoom.py`)

Python renderer built from the models above: hexes via `$012EDA`, units via
`$012B3A` (sprite rule for overlay terrain), cursor 4x4 sprite tile `$8001`. Terrain tile
patterns come from VRAM (the map screen has the whole terrain tile set loaded), unit graphics
from ROM (so units outside the game's view work too).

- **Map pixel coordinates:** hex (X, Y) at x = 24·X (+12 on odd Y), y = 16·Y; the game's map
  viewport (screen x 32–303, y 8–167; edge mask sprites and status bar outside) shows
  screen = map − (24·`$CD20` − 10, 16·`$CD21` − 8). Hex `$CD21` is plane row 1: the copy
  `$0059BE` sends the 24-row buffer starting at row `$CD24` to VRAM row 1, in two parts (wrap).
- **Cursor:** the 32x32 sprite sits at (−8, −8) from the hex's 24x16 block.
- **Check against the game** (`mapzoom.py check`, 9 captures): every
  (palette index, shadow) of the render maps to exactly one screen colour over the whole
  viewport (43,520 pixels) – plain map, movement range, range with moved cursor, cancel, tank
  range, Maginot start view; the other differences are all explained: open command menu /
  target info window (inside their boxes), the right 6 px of the viewport (x ≥ 298) where the
  game shows plane columns it did not draw, the two road hexes next to the damaged road in
  Maginot (`$012EDA` section), and palette 3 entries 7–12 in a sea view – the water colours the
  game cycles every 16 frames (`$005374`, tables `$0342B0`; the VDP dump and the screenshot were
  ~20 frames apart).
- **Fog safety:** units are hidden by record byte `$10` bit 7 (as `$012D4A` does), not by
  `$FF7000`: with fog, every shown unit stood on a lit hex and every hidden enemy on a fogged
  one (scenario 0: 7/5, Maginot: 71/50); during the movement range `$FF7000` holds the range, byte `$10`
  still the spotting – so the zoomed view shows no more enemies than the game does.

## Zoomed-out HD map (`recomp/game/ad_mapzoom.c`)

The map at half size in the HD frame: original art, twice the area. On by default; F9 or
System menu → System → "HD map" (`menu.md`) toggles, the choice is kept in `ad-port.ini` (`hd_map`, on by default); `AD_MAP_ZOOM=0|1` overrides it for one launch. The 1x
frame and everything the game reads are untouched. Not possible inside the VDP (the planes hold
64x32 tiles and the game only draws around its own view), so it is a host-side renderer.

- **Framework hooks** (patches 0008, 0010; `recompiler.md`): per HD line a layer hook may
  rewrite the sampled planes A/B (byte = priority<<7 | opaque<<6 | palette<<4 | colour), a
  sprite hook may leave a sprite out or move it sideways, a margin hook fills the side margins.
  Sprites, shadow/highlight and palette are composed afterwards as usual, so fades, water
  cycling, fog shading and menu sprites keep working.
- **Rendering:** a C port of `tools/mapzoom.py`. Once per frame the area is built – terrain
  into a plane B buffer, grid/units/cursor into a plane A buffer, 2 map pixels per screen pixel –
  and replaces both planes on screen lines 8–167.
- **16:9:** with side margins of 39 screen px (`GENESIS_HD_MARGIN=39`, set by `tools/run.sh`;
  `--no-wide` = off) the frame is 398x224 (HD 1592x896) and the area 796 map px wide instead of
  640. Only the zoomed map fills the margins; every other screen, the status bar's lines and
  the game's own map keep the 320 px picture in the middle, with the camouflage frame in the
  margins (`frame.md`; black in the intro and with `AD_FRAME=0`).
- **Camera:** starts centred on the game's view and moves only when the view (incl. fine
  scroll `$CD14`/`$CD16`) comes within 48/32 map px of the area's edge, gliding a quarter of
  the way per frame; clamped to the map bounds (a smaller map is centred). It must not follow
  `$CD20`/`$CD21` directly: the game scrolls its view 5 columns at a time in uneven steps.
- **Border columns:** the black mask sprites (tile `$011`) cover 10 screen px = 20 map px on
  each side. Without margins the area may run 20 map px past the map's side bounds so the
  outermost hex column is not under them; with margins they are left out instead.
- **Map-anchored sprites** are left out of the HD frame and drawn into the area:
  - cursor (4x4, tile `$001`): placed from RAM – hex (`$CD1E`+`$CD20`, `$CD1F`+`$CD21`) − (8, 8);
    while the view scrolls the cursor object `$FFD1D0` is a hex ahead or behind, so the sprite
    only tells whether the cursor is shown;
  - 3x2 unit sprites (tiles `$094`+): units on overlay terrain are drawn from RAM; the sprites
    are copied only while a unit moves (a record with Y = `$80`–`$BF`; records with Y = `$FE`
    exist permanently in some saves and must not count);
  - other 3x2 sprites (effects such as the miss puff) are always copied.
  Position: map = screen + (24·X − 10, 16·Y − 8) + 8·(fine x, fine y) with the view **that
  belongs to the sprite table in VRAM**, not the current one: the table is built by the frame
  step `$01405A` and can reach VRAM a frame later, so the view is stored at each frame step and
  applied only when the table in VRAM has changed. Using the current view gave ghosts up to
  120 map px off during scrolls.
- **A moving unit:** its record's Y byte has bit 7 set (X unchanged) and the game shows it as
  the 3x2 sprite tile `$094` stepping along the path; the cursor RAM follows the path but the
  cursor sprite is hidden.
- **Active only while the hex map is on screen:** plane B's per-cell horizontal scroll shows
  the hex stagger – cell rows 1–6 hold two non-zero values 12 px apart in pairs, in either
  phase (the pairs start at row 2 for a frame when the view moves by a hex row). All other
  screens have 0 there. `$FF0110` and `$FFCDA3` are not usable: when an attack is confirmed
  they change ~6 frames before the map leaves the screen.
- **The game's view scroll takes no game time in the zoom:** the scroll routines
  `$915E`/`$91FA`/`$9298`/`$9348` (called only from `$8856–$8862` and `$90BE–$90CA`) end each
  step in the frame step `$01405A`; with the zoom active a hook returns from it at once
  (`AD_SCROLL_SKIP=0` = off). The planes are RAM shadows the V-int copies whole, so the next
  real frame shows the finished scroll. Fast-forward is no alternative: the music runs on the
  Z80 and YM timers and would jump at every scroll (`sound.md`).
- **Menus over the cursor:** the game puts the command menu at x 36 whatever the unit's
  position. Once per frame the bounding box of the menu/window sprites in the map area is
  checked against the cursor's zoomed hex; on overlap the boxes are mirrored to the other side
  (sideways only).
- Savestates do not restore this game (garbled screen): tests play from boot.

Open: the terrain at half size is the pixel-doubled original (no HD art); other map
animations may need to be classed as map sprites; jp/en builds are not rebuilt.
