# Text map (JP Rev A)

Evidence: call/pointer analysis of the ROM, decoded with `tools/adtext.py`
(character map `translation/charmap.txt`). Full list: `tools/adtext.py catalog ROM --out
build/text/catalog-jp.tsv` (1,510 strings, ~9,500 characters; not committed, generated).
Encoding and font: `text.md`. Addresses apply to the JP ROM only – the EN patch moved the tables.

## Fonts and draw routines

| Routine | Font | String format | Calls |
|---|---|---|---|
| `$008166` / `$00816A` | 16x16 at `$03C86A`, 862 glyphs incl. ~700 kanji | length byte + codes (1 or 2 bytes) | ~120 |
| `$008104` / `$008108` | 8x8 at `$03850E` (169 glyphs: codes `$00–$A7` as in the 16x16 font, `$A8+` icons), preloaded to VRAM by `$0081FE` | length byte + 1-byte codes | ~80 |
| `$008128` | 8x8, glyph rendered on the fly | length byte + 1-byte codes | 12 |
| `$008124` / `$008162` | 8x8 | **8 characters, no length byte** (names in records) | ~25 |
| `$0082C0` / `$0082D8` | 8x8 digits | number output (divu 10000) | ~75 |

The 8x8 font has no kanji: everything drawn through `$8104`–`$8162` is Latin/katakana.
The two fonts share the codes `$00–$A7`, so one character map serves both.

## Text areas

| Section | Address | Entries | Format | Content | Font |
|---|---|---|---|---|---|
| block | `$0EF107–$0EFF95` | 367 | length | weather, climate zones, menus, commands, settings, unit stat labels, 49 error messages, ending texts, intro | mostly 16x16 |
| armies | `$0233F0` | 82 × 9 B | length (8 chars) | nations, army groups, fronts, commanders (ドイツ テイコク, グーデリアン, ＬＥＥＢ ＡＧｒ) | 8x8 |
| misc | `$0236D2` | 1 | length | ＰＡＸ ＧＥＲＭＡＮＡ | 8x8 |
| movement | `$02376A` | 23 × 4 B | length (3 chars) | movement types (装軌基, 半装軌, 鉄道Ｅ, 歩兵雪 …) | 16x16 |
| classes | `$0237C6` | 44 × 7 B | length (6 chars) | unit classes (戦闘機, 急降下爆撃機, 駆逐戦車 …) | 16x16 |
| terrain | `$02AE76` | 99 × 8 B | fixed 8 | terrain (ヘイチ, モリ, トシ Ｂ１, クウコウ, シュト …) | 8x8 |
| units | `$02B1F2` | 690 × 34 B | fixed 8 at record start | unit names (Ｂｆ１０９Ｅ, パンターＤ, ホヘイ ３９ …); table base referenced 78× (`lea $2B1F2` + index × 34) | 8x8 |
| weapons | `$033DB6` | 159 × 8 B | fixed 8 | weapons (２０㎜キカンホウ, ２５０㎏バクダン, ８８㎜ホウＬ７１ …) | 8x8 |
| scenarios | `$07EEB8` | 45 × 112 B | fixed 8 at record start | scenario names (ケース ホワイト … アイランドＣｐ, USERMAKE first) | 8x8 |
| missions | `$023EB6` packed, offsets `$023E5E` | 44 (43 distinct) | LZSS, rows with control byte | campaign briefings before each map (`briefings.md`) | 16x16 |
| results | `$02539A` packed, offsets `$0252DE` | 94 (93 distinct) | LZSS, rows with control byte | campaign texts after each battle (`briefings.md`) | 16x16 |

Inside the block (`catalog` column `source`): `ref` = a pointer to it exists, `seq` = read
after the previous string (second lines, lists such as the error messages).
"Cutscenes" are three texts in the block, all 16x16:
- **Intro** `$0EFB58–$0EFC59`: epigraph この悲劇が繰り返されないことを願って, captions 1919–1939.
- **Post-war timeline** `$0EFC70–$0EFE36`: 1945–1949, then a Churchill quote (8 lines).
- **Victory epilogue** `$0EFE89–$0EFF49` (7 lines), result lines `$0EFE49–$0EFE71`.
  The text is typed over the photo in the original too (same layout in the tr build with
  `AD_LANG=jp`); the English lines keep that layout.

## Translation budget

- 16x16 text (block, movement, classes): proportional English via extended glyphs
  (`translation-rom.md`); each string can be moved, so length is limited by the screen, not the ROM.
- 8x8 text (names, terrain, weapons, scenarios, armies): **fixed 8 characters**, in records the
  code indexes by stride. The 8x8 font already has Latin letters; English must fit 8 characters
  (abbreviations) unless the name routines are changed. Katakana names are mostly transcriptions
  of Western names (パンター = Panther) – straightforward.

## Not text / not mapped yet

- `$0EF038–$0EF106`: tables (letter sets ＡＢＣＤ…, unit class letters) – data, not translated.
- Graphics with lettering: SEGA/SystemSoft logos, 資料提供 credits screen, title logo with
  subtitle ドイツ電撃作戦 (tiles, `text.md` intro table). **Compressed** (evidence: VRAM
  dumps at frames 1020 and 2400, JP build; of ~1,300 non-blank tiles only 2–3 occur raw in the
  ROM, all at `$0D5xxx`). Replacing them needs the decompressor or a VRAM overwrite after it ran.
- The compressed data around `$026D60` with katakana fragments (アレキサンドリア, スエズ,
  ムッソリーニ) is the packed results block (`$02539A–$0280EB`, `briefings.md`).
- 45 text-routine calls take a0 from RAM (records copied from the tables above); not every source
  is traced. Text built at runtime (numbers, `$0082C0`) needs no translation.
