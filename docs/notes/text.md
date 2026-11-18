# Text, font, encoding

## Observations

- In the Nebelwurfer patch the menus are English and the Japanese cutscene texts are broken
  (a mix of English and Japanese characters): the patch overwrote glyphs that menus and
  cutscene texts share.

## Encoding of menu texts (evidence: decoding)

- Bytes at `$0EF12F`, `$0EF138`, `$0EF141` decode with `'A'=$15` (= ASCII − `$2C`) to
  CONTINUE, STANDARD, CAMPAIGN. Preceding length byte = character count − 1 (`$07` → 8).
- These texts are already Latin in the JP ROM; the EN patch changes 2,525 bytes in the
  region `$0EF000–$0F0000`.
- Confirmed: these are the glyph indices of the 16x16 font below; kana and kanji
  follow `Z` in the same table.

## Font and string encoding (evidence: VRAM dump + ROM search + disassembly)

- **Font** at `$03C86A`: 862 glyphs (index `$000–$35D`), 16x16, 1 bpp, 32 bytes each as four
  8x8 blocks (top-left, top-right, bottom-left, bottom-right; MSB = left pixel).
  Content: digits, Ⅰ–Ⅹ, space (`$14`), A–Z (`$15`), a–z (`$2F`), katakana (`$49`), symbols,
  kanji/hiragana from `$A8`. Character map: `translation/charmap.txt` (every intro glyph checked
  against the screen).
  Evidence: glyphs of a caption in VRAM (dump at frame 3600, tiles `$4DC`+) found 1:1 in the ROM.
- **String:** length byte (glyph count − 1), then one code per glyph. Code < `$FD` = index;
  `$FD/$FE/$FF xx` = index `$FD + $000/$100/$200 + xx`. No compression.
  Example `$0EFB92`: `0C 01 09 02 03 FD CC 14 7C 98 8A 79 8A FD B1 FF 60` = １９２３年　ミュンヘン一揆.
- **Draw routine** `$008166` (a0 = string, a1 = name-table buffer, `$FFCD04` = first VRAM tile,
  `$FFCD06/07` = ink/background colour): per glyph `$0081B8` decodes the code and fetches the glyph
  via `lea $3C86A,a6` at `$0081E0` – the only reference to the font – and `$00820C` expands 1 bpp
  to 4 bpp into VRAM (or a RAM buffer at `$FFF000` when bit 7 of `$FFCD35` is set). Each glyph takes
  4 new VRAM tiles and 2x2 name-table cells.
- **Why the EN patch breaks text:** it changes `$03D18D–$0409C7`, i.e. glyphs of this font, and
  rewrote the string area `$0EF35B–$0EFF97`. Shared kanji glyphs became Latin.
- Tool: `tools/adtext.py` (decode strings, dump the intro, catalog of all text).
- Where all text is: `text-map.md`.

## Intro captions (evidence: disassembly + `tools/adtext.py intro`)

Each caption: `lea <string>,a0` / `lea <buffer>,a1` / `bsr $8166`; a second line follows the first
string directly in memory and is drawn with a0 as left by the first call.

| `lea` at | String | Lines | JP |
|---|---|---|---|
| `$000EF2` | `$0EFB7D` | 1 | １９１９年　ベルサイユ条約調印 |
| `$000FBE` | `$0EFB92` | 1 | １９２３年　ミュンヘン一揆 |
| `$000FE0` | `$0EFBA3` | 1 | １９３３年　ヒトラー内閣成立 |
| `$00109A` | `$0EFBB7` | 2 | １９３４年　ヒンデンブルグ死去 / ヒトラー総統就任 |
| `$001170` | `$0EFBDD` | 2 | １９３６年　独、ラインラント進駐 / 日独防共協定調印 |
| `$00128C` | `$0EFC09` | 2 | １９３８年　独、オーストリア併合 / ミュンヘン会談 |
| `$0013AC` | `$0EFC2F` | 1 | １９３８年　ズデーテン、独へ割譲 |
| `$0014B8` | `$0EFC46` | 2 | １９３９年　独、チェコ解体 / 独ソ不可侵条約締結 |

The EN patch also mistranslated some (1934 "Opposition Crushed", 1936 "Spanish Civil War Begins").
Line start: column 3 (x = 24); at most 18 glyphs per line on screen.

## The EN patch changes no code (evidence: byte diff)

Diff JP ↔ EN by range: header 1 byte (checksum), `$000200–$023000` 0,
`$023000–$041000` 15,475, `$041000–$0EF000` 320, `$0EF000–$0F0000` 2,525, `$0F0000–$100000` 0.
Seeds and hook sites untouched → the recompiler generates the same code for both ROMs.

## Open

- Cutscene texts: answered in `text-map.md` (same routine and font, in the block `$0EF000`).

## Intro / attract sequence (evidence: scripted screenshots, EN build)

Frame numbers from power-on, `--turbo`, no input; the sequence loops after ~5,340 frames.

| Frames | Content | EN ROM | Kind |
|---|---|---|---|
| ~0–900 | SEGA, SystemSoft logos | – | graphics |
| ~900–1,350 | `資料提供 / 戦車マガジン / 航空情報` (material provided by Sensha Magazine / Koku Joho) | **Japanese** | graphics (logo tiles) |
| ~1,350–1,800 | "English Translation By Nebelwurfer HQ – 2002" | added by the patch | text/tiles |
| ~1,950–2,950 | Title screen, subtitle `—ドイツ電撃作戦—` (German Blitzkrieg) | **Japanese** | graphics |
| ~2,970–5,300 | History captions 1919–1939 over the map | English | font text, see "Intro captions" above |

EN caption flaws: `Versailles TreatyendWW 1`, `OppositionCrushed` (missing spaces).
The intro is therefore *not* affected by the broken cutscene text; the untranslated parts are graphics.
