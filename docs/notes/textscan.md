# Text scan – Japanese leftovers on screen

Finds Japanese glyphs of the JP fonts on the running game's screen – leftovers in the tr build.

## How it works

`tools/textscan.py` reads the VDP state (VRAM, VSRAM, plane addresses, scroll mode) through the
runner's TCP debug server (`vdp_state`, ~10 ms per snapshot) while the game runs, and looks for
glyphs of the JP ROM's fonts (`text-map.md`) in the visible cells of planes A and B:

- **16x16** (`$03C86A`): a 2x2 cell block whose four tiles carry the four quarters of one
  Japanese glyph (blank quarters: single-colour tile). Single quarters are not enough: in the intro
  VRAM (frame 1100, logos only) six graphics tiles matched a kanji quarter by chance.
- **8x8** (`$03850E`, 1 bpp, 8 bytes per glyph, same codes `$00–$A7`; checked: `$49` = ア):
  a Japanese glyph whose pattern no Latin glyph shares, next to another 8x8 font cell.
- A tile counts when it has exactly two colours and one of them, taken as ink, gives the pattern –
  ink and background colours vary per text (`$FFCD06/07`).
- Japanese = hiragana, katakana (with ー ・), kanji, 、。々 (charmap); full-width Latin, digits,
  Ⅰ–Ⅹ, ㎜ ㎏ and symbols are not.

Not detected: lettering inside graphics (logos, `graphics.md`) – it is not drawn from the fonts.
Not checked: English text that runs past its box (`tools/translate_rom.py --measure` checks widths
offline).

## VDP layout of the game (evidence: vdp_state, jp intro and map)

- Planes A and B share `$E000` (64x64 cells); plane B is scrolled down by 256 px (VSRAM[1] = `$100`),
  so the two show different halves of the table. H40, full-screen vertical scroll; horizontal
  scroll table `$DC00`.
- **No window plane:** the register table at `$00502E` (`8004 8114 8238 832C 8407 856C … 9100 9200`)
  sets window position 0; a search of `$000000–$0DFFFF` for `move.w #$91xx` / `#$92xx` (to Dn,
  (An), absolute) found no other write. **Hypothesis** until a run shows the window never appears:
  registers written through computed values would escape the search. The window base (`$B000`)
  then lies in tile data; scanning it gave nonsense katakana (ゼノ, ヌヌ) on the map screen, so
  the tool ignores it.
- The debug server reports neither window position nor sprites; text drawn as sprites would be
  missed (none seen so far).

## Validation

| Run | Samples | Japanese lines |
|---|---|---|
| jp, intro to frame 3700 | 1,836 | epigraph + all captions shown so far (この悲劇が…, 年 ベルサイユ条約調印, …) |
| jp, route `standard.txt` | 1,830 | 41: STANDARD menu (ロード … 開始), scenario list (ケース ホワイト …), status pages (ドイツ テイコク, ポーランド), turn screen (天候 晴, 累積度 通常), map status bar (テキダンヘイ, シュト) |
| tr, intro to frame 5400 | 2,696 | 0 |
| tr, route `standard.txt` | 1,849 | 0 |

The tr screenshots of the same screens show English throughout.

Frames with the display off or a single-colour palette are skipped: while the screen is off
the game loads tiles and the name tables hold leftovers or font sheets (イウエオ… over a whole
plane), which gave false lines.

Two play sessions with `watch` (tr, ~170,000 and ~912,000 frames, 35,000 samples): no Japanese
text on a visible screen. Not covered by any scan: rare error messages.

## Notes for routes

- STANDARD menu: the cursor stays on Load until a scenario is loaded; the 8-entry menu wraps.
- Status: two pages (occupation, units by type); C turns the page, C on page 2 closes it.
- A scripted run may change settings in SRAM, so `textscan.py run` backs up the build folder's
  `*.srm` and restores them afterwards.
- `tools/textscan/standard.txt` is not reliable: single presses are sometimes not taken, so
  fixed press counts drift (it ended in the System/Sound menus in a turbo run). Reliable is
  reading the highlighted row from a screenshot (`work-environment.md`).
