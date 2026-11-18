# HD graphics (4x presentation)

The same look, but crisp: the graphics redrawn at a higher resolution, not filtered.

## How it works

Framework patch `0007-vdp-hd-tile-pack-presentation` (end of `runner/video/genesis_vdp.c`):

- The VDP renders every raster line a second time at scale 4 (1280x896) into its own frame.
  Every 8x8 tile is looked up in an **HD tile pack**; a hit supplies a redrawn tile, a miss
  samples the original pattern (pixel repeated). Planes A/B, window and sprites go through
  the same priority / transparency / shadow-highlight composition as the 1x renderer, per
  sub-pixel. The 1x frame is still produced as before (screenshots, hashes, status flags).
- HD texels are **4-bit palette indices**, like VRAM patterns: palette rows, fades, fog of war
  (shadow/highlight) keep working, and the redraws are bound to the game's 16 colours per tile.
- Presentation only: sprite overflow/collision stay with the 1x evaluation; nothing the game
  can read changes. Unsupported modes (interlace 2, widescreen, host-sprite extensions) fall
  back to the pixel-repeated 1x row.
- Loaded with `GENESIS_HD_PACK=<file>` (`GENESIS_HD_SCALE=2|4`, default 4). `tools/run.sh`
  sets it when `build/hd/pack.bin` exists (`--no-hd` skips it). **F10** in the game switches
  between HD and the original graphics. The window then requests Retina resolution
  (`SDL_WINDOW_ALLOW_HIGHDPI`); the HD frame is scaled linearly into the window.
- During fast-forward the HD frame is rendered only for presented frames.
- Screenshots (input script `SCREENSHOT`, debug server `screenshot`) also write `<name>.hd.png`.

### Pack entries (`GHDPACK1`)

| Kind | Key | Texels | Used for |
|---|---|---|---|
| 0 full | the 32 pattern bytes | (8t)² bytes, palette index 0–15 | redrawn art (`tools/hdart.py`) |
| 1 shape | 8 bytes 1bpp mask of a two-colour tile (bit = higher nibble) | (8t)² bits; 0/1 → lower/higher nibble | 8x8 font |
| 2 cell | masks of four consecutive tiles TL TR BL BR (one colour pair) + quarter 0–3 | as shape | 16x16 text cells |

Lookup order: full, cell (the tile tried as quarter 0–3 of a group starting 0–3 tiles before
it), shape. **Cell alignment** (patch 0009): a nearly blank quarter can complete a
wrong group (the one-pixel foot of an "l" spilling into the next quarter matched another text's
cell). The alignment of an already resolved neighbour tile (±3) of the same
group is now tried first. t = 1, 2, 4 or 8 (scale of the redraw); the renderer resamples to its own scale.

Why **cell** entries: English text is set proportionally and cut into 16x16 cells, so an 8x8
piece of a letter does not say which letters it belongs to. Keyed by the 8x8 piece alone,
30 % of the 4435 text pieces had several different 4x versions (by up to 300 of 1024 texels –
visible wrong serifs at the seams). Keyed by the whole cell (game fonts, before the typeface layout): 386 of 7409 cells (5 %), all
identical 1x cells that come from different text.

**Sprite text (map command menus).** The unit command menu (Move / Attack / Occupy / Merge /
Supply) is made of sprites (sprites 10–17 in scenario 0, 4x4 and 2x4 cells
at x 36/68, frame and text drawn into the same sprite tiles). Sprite tiles are numbered down the
columns, and a 16x16 text cell crosses the edge between two sprites (cell 2 of each label: right
half in the next sprite), so the "four consecutive tiles" rule does not find it. For unflipped
sprites the renderer keeps a per-frame map of sprite tiles by screen position and looks the cell
up from the tiles at the neighbouring screen positions (first sprite in the link order wins).
Checked: all 40 text tiles of the five labels resolve (offline check against the pack, then in
the game); HD frame vs 4x enlargement differs only in the menu text and the status bar.

Evidence for the VRAM layout of a 16x16 glyph (VDP dump, STANDARD menu, tr): name-table rows 5/6
of "Status" hold `$087 $088` / `$089 $08A`, `$08B $08C` / `$08D $08E` … – four consecutive tiles
TL, TR, BL, BR (the font's quarter order), groups not aligned to 4.

## Text: set by a typeface (tools/hd/typeface.py, tools/hdpack.py)

The translated text is **set by a typeface, not by the game's pixel fonts** (their letter
heights and spacing are uneven, and the big font has only 2 rows below the baseline).
`tools/hd/typeface.py` builds text fonts from **Nunito Sans Medium** (SIL OFL 1.1, files and how
they were cut in `tools/hd/fonts/`; an open typeface, so a release may ship the glyphs). The
big size uses width 94 % of the family's width axis: at 100 % "Weather" misses its 64 px box by
2 px and ten menu strings fall back to the small size; at 94 % the big/small split is 78/257:

| Size | Used for | Typeface | Room (1x rows) |
|---|---|---|---|
| big | 16x16 strings, intro captions, briefings | Nunito Sans Medium, width 94 | rows 1–15, cap ≤ 13 px (≈ 11 px) |
| small | tight boxes (was `translation/font/small.txt`) | Nunito Sans Medium, width 75 | rows 5–14, cap ≤ 7 px |
| 8x8 | the game's 8x8 font (names, numbers, status bar, unit stats) – HD only | Nunito Sans Medium, width 94 | rows 0–7 |

- One scale per size, so capitals plus the deepest descender fit the rows; every glyph on one
  baseline, descenders below it.
- **Spacing from the typeface:** every glyph is a slot of its advance width rounded to whole 1x
  pixels (the space too). `translate_rom.py` sets the 1x text with these slots (1x glyphs are
  the typeface rasterized at 1x), `hdpack.py` gives every 1x column its 4x columns from the
  same font – so 1x and HD stay in register and each 1x cell maps to one HD version.
- The **small size** uses the condensed cut: with the regular cut 21 strings (Deploy, Occupy,
  Disband, Rng, Arm, Wet, Whl Amph …) no longer fit their boxes; with the condensed cut all
  331 do. The big size fits better than the game font did (182 strings in the big size, was 126).
- Glyphs the game places itself keep their positions: the 8x8 font and the original 16x16
  digits / letters used as codes, plus the game's full-width punctuation (`． ： ／ （ ） ＝ ＄ ％`,
  e.g. the dots in the turn screen's dates) get the typeface glyph centred on the 1x ink, on the
  size's baseline. Glyphs taller than the row (`$`, brackets) shrink to fit, still on the
  baseline (the 8x8 `$` was cut off at the top). The 8x8 `．` and `：` are drawn too. Not redrawn: kana of the 8x8 font, `$A8+` icons, the 8x8 bar
  and apostrophe (`― ’`).
- **One-cell symbols** (`Ⅱ Ⅲ Ⅳ Ⅵ Ⅶ Ⅷ Ⅸ ㎜ ㎏`, both fonts) are set as several letters of the
  typeface ("III", "mm"), at the size's height on its baseline (`typeface.compose`): mid-cell and
  at most 6.5 px wide in the 8x8 font, on the 1x ink in the 16x16 font; the condensed cut when
  the regular one is too wide, then squeezed horizontally.
- Characters the typeface lacks fall back to the game glyph (pixel-scaled in HD).
- `translate_rom.py --game-font` builds the ROM with the game's pixel fonts as before.
- Rasterizing: CoreText via `tools/hd/glyphs.swift` (font file or PostScript name; ink box,
  baseline offset, advance); fonts cached in `build/hd/typeface-*.json`.
- Cells with two possible HD versions (identical 1x cell, e.g. the left stem of "n" and "m"):
  483 of 7448 (6.5 %), majority used.

## Art (tools/hdart.py)

1. Collect: `tools/textscan.py debug on`, start the game, `tools/hdart.py watch` while playing
   (or `add SNAPSHOT.json`). Records every tile on screen in `assets/hd/catalog.json`.
2. `tools/hdart.py export`: one sheet per screen layer where tiles were first seen,
   `assets/hd/sheets/NNN-A|B|S.png` (1280x896 = the screen at 4x, only new tiles, text left
   out), indexed PNG with that screen's 64 colours. Pictures (intro photos, Europe map, logos)
   stay whole; repeated tiles (hex terrain) appear once – a redraw changes every copy.
3. Redraw over the enlarged pixels, colours only from the tile's own palette row (indexed mode,
   e.g. Aseprite/GIMP; RGB(A) works too, mapped to the nearest colour of the row).
4. `tools/hdart.py import` (changed cells → `build/hd/art.bin`), then `tools/hdpack.py build`.

`assets/` is not in the repository (tiles extracted from the ROM). **Open:** where the redrawn
art is kept and versioned (it is derived from ROM tiles).

First collection (intro, menus, map of scenario 0): 3094 tiles, 2624 exported in 19 sheets.
No art is in the pack yet.

## Verification

- No pack, scale 4: all 12 intro frames (340–5200) of the HD screenshot are identical to the
  1x screenshot enlarged 4x (nearest), byte for byte.
- With the text pack, map of scenario 0 (fog of war on, units): HD frame identical to the 4x
  enlargement except raster lines 176–207 (status bar text).
- Speed: 5000 turbo frames 42.3 s without, 42.2 s with HD.

**Zoomed-out map and 16:9:** see `map.md`, "Zoomed-out HD map".
