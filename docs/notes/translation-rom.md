# Translated ROM (variant tr)

Evidence: build + headless run of the intro (frames 0–5400), video
`build/video/intro-tr.mp4`.

`tools/build.sh --rom tr` generates `build/rom/ad-tr.md` from the JP ROM (`tools/translate_rom.py`)
and builds it like the other variants. The ROM is 3 MiB and runs in the normal runner; the
recompiler finds the new routine through the `jsr` (native, not interpreted).

## Layout

| Range | Content |
|---|---|
| `$000000–$0FFFFF` | JP ROM, patched: `$0081E0`, `$0081B8`, the briefing lookups `$001EB4` / `$002324`, the `lea` operands of the intro captions and of two packed intro graphics (`$000642`, `$000B70`), the name tables (in place); header ROM end `$2FFFFF`, checksum |
| `$100000` | glyph lookup routine |
| `$100060` | string redirect routine (40 bytes, to `$100087`) |
| `$1000C0`, `$1000D0` | briefing lookup routines (missions, results; `briefings.md`) |
| `$100100` | redirect table: (original address.l, copy address.l) …, 0 |
| `$101FEC` | long pointer to six long pointers and their strings: the System settings rows "Fast enemy turn" and "Enemy battles" (labels, translated), then the values 1x / 2x / 4x / MAX (the same in every language; `menu.md`) |
| `$101FF0` | long pointers to strings the port adds (no JP original): [0] label "HD map" of the System settings screen, [1] (`$101FF4`) the eight "CAMPAIGN START 19xx" strings of the title menu's start-year row (`menu.md`); read by `ad_spec.c` |
| `$101FF8` | long pointer to the language block (below) |
| `$101FFC` | long pointer to two strings the port adds: the Record menu row "Restart" and its dialog title (`campaign.md`, "Restart"), each as long as the "Give up" string it stands in for |
| `$102000` | new strings (same format as the original, `text.md`), then the unpacked English briefing blocks and their long-pointer tables, the repacked intro graphics, the strings of the "Language" row and the language block |
| up to `$1FFFFF` | room for text data (used up to `$169F6E`) |
| `$200000–$20FFFF` | filler: the battery RAM lies over it (`saving.md`) |
| `$210000` | extended glyphs, 32 bytes each, same format as the font (22,223, up to `$2BD9E0`; room to `$2FFFFF`) |

## Glyph lookup patch

`$0081E0` `lea $3C86A.l,a6 / adda.w d4,a6` (d4.w = index × 32) → `jsr $100000.l / nop`.
The routine keeps the original path; for index `$3ED` (codes `FF F0`) it reads two more string
bytes as glyph number n and returns a6 = glyph base + n × 32 (the base operand is `$210000`). The font ends at `$35D`, so `FF F0`
never occurs in original text. Room for 65,536 extended glyphs.

## English text

The English part of a line is set proportionally from the Latin glyphs of the game font (ink width
+ 1 px, space 6 px, `-` `.` `,` `'` `ü` drawn in the tool) and cut into 16 px cells; each cell is an
extended glyph (identical cells shared). The monospaced prefix (year, indent) uses normal codes.
Intro budget: 4-cell prefix + 14 cells (8 px gap included) from column 3 → ends at x ≤ 312.
Every cell costs 4 VRAM tiles like an original glyph; the intro uses tiles from `$4DC` with free
space up to ~`$6C0` (VRAM dump at frame 3600).

## Scripts

`translation/script/*.toml`: per caption the `lea` site, the original address and the lines with
`jp` (checked against the ROM on every build), `fixed` and `text`. The build stops when a line is
too long or the JP text does not match.

## Name tables (8x8, fixed 8 characters)

`translation/script/names-<section>.toml`: `[table] section` names an entry of
`adtext.TEXT_TABLES` (`text-map.md`), `[names]` maps each distinct JP name to English (≤ 8
characters). The build overwrites every record with that JP name in place (padded with spaces;
for `armies` after the length byte 7), stops on an unknown JP name or a name longer than 8, and
prints `section translated/total`. Names already in Latin letters stay as they are.
Characters: ASCII letters, digits, space, `. : - / ' ( ) = $ %` (mapped to the full-width codes,
`-` → `―` `$9D`), plus `Ⅰ–Ⅹ`, `㎜`, `㎏` (one character each).

State: terrain 99/99, scenarios 44/45 (USERMAKE is Latin), armies 59/82,
units 358/690, weapons 145/159 – the rest were Latin already; no Japanese left in these tables
(`tools/adtext.py catalog`).

## String redirect (16x16 text outside the intro)

`$0081B8` (start of the glyph decoder; `$00816A` calls it once per string with a0 = string start
+ 1) `andi.w #$F,d1 / andi.w #$F,d2` → `jsr $100060.l / nop`. The routine does both `andi` and looks
a0 − 1 up in the table at `$100100` (linear search, 0 ends it); on a hit a0 = copy + 1.
The lookup compares only the low 24 bits. The works menu table `$00BA4E` (10-byte records: word, string
address.l, handler.l) keeps the item index in the top byte of the address (`$010EF378` …
`$070EF3A7`); `$00BABA` reads it back (`rol.l #8`) as the index into `$00BF96`. The 68000 ignores
the top byte, so the game draws fine, but the 32-bit compare only matched item 0 (`$000EF36F`).
The caller restores a0 from the stack (`$00BAA8`), so losing the top byte on a hit is harmless. d0, d3, d4,
a6 are free at that point (the decoder sets them before use).

Why a lookup instead of patching pointers: block strings are reached through `lea`, pointer
tables, fixed-stride tables (weather 3 bytes, movement 4, classes 7) and by reading on after the
previous string (second lines, lists). The lookup works for all of them without knowing the
references:
- the **glyph count stays** (the count is read from the original length byte in `$008166` before
  the redirect; boxes, VRAM tiles and screen clearing stay as designed) – English is padded with
  blanks;
- every **run** of consecutive strings that contains a translated one is copied in its original
  order (untranslated members byte for byte), so "read the next string" continues in the copy;
- the original bytes stay untouched (fixed-stride indexing still finds the original address).

Scripts `translation/script/text-*.toml`, `[[string]]` with `addr`, `jp` (checked), `en` and
options `align`, `font`, `group` (one member needs the small font → the whole group uses it,
so lists look uniform), `fixed` (game-font prefix such as a year), `indent` (blank cells),
`parts` (`[[cell, text], …]` for strings with blanks reserved for numbers, e.g. `X=` / `Y=`).
**Typeface layout:** the English text is set with fonts drawn from Nunito Sans
(`tools/hd/typeface.py`, font files in `tools/hd/fonts/`; small size: its condensed width): slots of the typeface's advance
widths, one baseline with descenders – see `hd-graphics.md`. `--game-font` sets it with the
game's pixel glyphs as before. The intro graphics (`[[graphic]]`) keep the game glyphs.
Alignment: **left by default**; centred only where the JP starts with 2+ blanks (timeline
captions).

**Small font** `translation/font/small.txt` (own design, 5x7 capitals, 1 px strokes, row 6 =
baseline, placed at row 5 of the cell): used when the game's Latin glyphs (≈ 8 px per letter) do
not fit – two-kanji command boxes are 32 px.

State: 335 strings (block, unit classes, movement types), 78 big / 257 small font. Text scans
of play sessions found no Japanese text on screen (`textscan.md`).

### Who reads string bytes (static audit)

Evidence: capstone scan of the JP ROM `$000000–$0EFFFF` (all `jsr`/`bsr` and `lea`/`move.l #`
forms), each site disassembled.
- The 16x16 font is referenced only at `$0081E0`; every 16x16 glyph goes through `$0081B8`.
- 118 calls of `$008166` / `$00816A` / `$0081B8`. No caller uses a0 after the call (the two that
  touch a0 restore it from the stack first: `$00B7F2`, `$00BAA4`), so nothing reads on in the copy
  except the draw routine itself. Typewriter loops (`$0018EE` epilogue, the briefing loops) call
  `$00816A` per glyph: the first call is redirected, the following ones read on in the copy.
- 205 references into the text block `$0EF107–$0EFF95`: 192 lead straight to a draw routine, the
  rest to wrappers that only draw (`$00D1BC/$00D1C2/$00D1F4` message line, `$00F78E` menu frame,
  `$011C66` dialog, `$010AC4`, `$009EE4`, `$00D390` 8x8 names). No routine compares, measures or
  copies string bytes; box sizes come from the original length byte, which is unchanged.
- So the escape `FF F0` is only ever seen by `$0081B8` and the patched lookup.
- Draw calls with a0 in RAM (not reached by the redirect, which matches ROM addresses): `$0021FA`
  (`$FFCC00`, 8 glyphs), `$00B7EA` (`$FFC800` records + `$10`, 8 glyphs), `$00CD04` / `$00E1A6`
  (unit record via `$FFCD10`, 8 glyphs). All are fixed 8-glyph name fields holding names copied
  from the in-place name tables, so they show the translated names. `$FFCC00` is the first save
  block: the scenario name and the army names are copied into the save (`saving.md`).

## Language block (English, German, French, Spanish, Japanese in one ROM)

Evidence: headless runs of the tr build (`tools/drive.py`): boot in German, French, Spanish and Japanese
(`AD_LANG`, stored choice), STANDARD menus, scenario list, turn screen, map, command and
system menus, campaign briefing of map 1, the System settings screen stepping de → jp → en →
de; nothing interpreted in these runs. Offline: the ROM with the Japanese records applied
differs from the JP ROM only at the code sites of this file and the header.

The languages differ in **data only**; the code patches serve all. The ROM as built is English.
The port (`recomp/game/ad_lang.c`) shows another language by putting the English bytes back and
writing that language's records over the ROM image in memory. The game has no checksum test
(no read of `$00018E`), so the changed image is harmless.

Block (pointer at `$101FF8`): `count.w, 0.w, label.l` (string of the "Language" row,
`menu.md`); per language `code` (2 ASCII characters), `0.w`, `value.l` (the row's value
string); then per language after the first its records `address.l, length.w, kind.w, bytes`
(padded to even), address 0 ends a language. Order = order of the row: en, de, fr, es, jp
(`LANGUAGES` in `translate_rom.py`). de 296 records / 9,165 bytes, fr 293 / 9,071, es 307 /
9,199, jp 718 / 15,650.

| Text | Japanese (original bytes) | A translation (German, French, Spanish) |
|---|---|---|
| 16x16 strings | first long of the redirect table `$100100` = 0: every lookup misses, the string is read at its original address | the whole redirect table, pointing at the language's own copies of the string runs |
| name tables | each translated name's original 8 bytes | the names that differ from English |
| briefings | both long-pointer tables with `$FF2000 + offset` (the rows the game unpacks to RAM) | both tables, pointing at the language's own unpacked copy |
| intro captions | the original lines over the English copy | its lines over the English copy |
| intro graphics | the original Nemesis data over the repacked one | its own repacked data |
| "HD map", "Language", "Restart", "Fast enemy turn", "Enemy battles" | – (stay English) | its strings, written over the English ones |

Kind 1 = scenario name, 2 = army name (the rest 0). Captions, graphics and the port's strings
get the room of the longest version. "GREAT" and "CAMPAIGN START 19xx" are the same in every
language (they sit next to original Latin text).

**A translation's files:** `translation/<code>/*.toml`, keyed to the entries of
`translation/script` – `[strings]` by `addr` (text, `parts` list, or `{ text, font }`),
`[captions]` by site, `[graphics]` by name, `[port]` by the English text, `[names.<section>]`
by the English name, `[[briefing]]` by block and offset. Whatever is left out stays English.
The build stops with the list of every string that does not fit its box. German: all 335
strings (66 big / 269 small font), 246 names, 8 captions, 136 briefings (1,697 rows); French:
72 / 263, 244 names, 1,632 rows; Spanish: 73 / 262, 256 names, 1,608 rows. The intro graphics
are lettered with the game's own Latin glyphs (no accents).

**Names in RAM:** the game copies the scenario name and the army names into the save blocks
(`saving.md`). On a switch, and every 64 V-ints (a save loaded from another language), any 8
bytes in `$FFC800–$FFC9FF` / `$FFCC00–$FFCCFF` that equal a kind 1/2 name of another language
are replaced by the current one's. Unit, weapon and terrain names are read from the ROM tables
on every draw.

**Stored:** `ad-port.ini` (`language = en|de|fr|es|jp`) in the data folder (`GENESIS_USER_DIR`, else
the working directory = the build folder); read at the first V-int, before any text is drawn.
`AD_LANG=en|de|fr|es|jp` overrides it at start. Without a stored `language` (first start, or
never switched) the system decides: `SDL_GetPreferredLocales()` (Windows display languages,
macOS preferred languages, in order), the first the block has (`ja` = `jp`), else English; not
stored, so it follows a change of the system language (log: `[ADS] Language from the system`).
Tested on Windows with `SDL_PREFERRED_LOCALES` (SDL's override): `fr_FR,en_US` → fr,
`it_IT,es_ES` → es, `ja_JP` → jp, `it_IT,nl_NL` → en. jp/en builds have no block and no row.

**HD:** the pack holds the cells of every translation (22,705); Japanese text shows the game's
glyphs enlarged. Each translation adds its string copies, briefing copy and glyphs to the ROM:
about 100 KB of text data and 4,500 glyph cells (143 KB). Five languages need 1.14 MiB, more
than the megabyte above `$100000` of a 2 MiB ROM – hence 3 MiB.

## Great-victory date on the turn screen

`apply_victory_date`: END moves one line down, a new line "GREAT <date>" (game Latin font, label
right-aligned with NOW/END) shows the last day of a great victory; code at `$101F00`, hook at
`$008BB8`, campaign only. Rule and checks: `campaign.md`.

## Campaign briefings and result texts

LZSS-packed, unpacked to `$FF2000` and typed out row by row – not reached by the string redirect.
Own lookup patch, English rows in an unpacked copy in the ROM: `briefings.md`.

## Intro graphics

The credits word 資料提供 and the title subtitle ドイツ電撃作戦 are lettering inside Nemesis-packed
tiles (`graphics.md`). `translate_rom.py` unpacks the block, clears the text area, sets the English
from `translation/script/graphics.toml` centred in the game's Latin font (colour index of the
original lettering, subtitle with a 1 px shadow in the original's dark shade), repacks it with
`tools/nemesis.py` after the briefings and redirects the `lea` at the call site. Checked by
screenshot (tr build, frames 330 and 2600): "Courtesy of" above the magazine logos, "Blitzkrieg"
between the original dashes. Not translated: the 大戦略 logo (game title) and the magazine logos.
