# Campaign briefings and result texts

Evidence: headless runs JP + tr (CAMPAIGN → first map, RAM dumps during the
briefing), disassembly (capstone), `tools/adtext.py briefings` (unpacked data identical to the RAM
dump `$FF2000–$FF411D`, JP build, briefing of map 1).

## Where the text is

Not in the text block `$0EF107–$0EFF95` and not raw in the ROM: two **LZSS-packed** blocks, each
unpacked to `$FF2000` before the screen is drawn.

| Block | Packed | Offset table | Entries | Unpacked | Index | Draw loop | Content |
|---|---|---|---|---|---|---|---|
| missions | `$023EB6–$0252DD` | `$023E5E` (44 words) | 43 distinct (13 = 43) | 8,478 B | `$FFCC37` (campaign map) | `$002336` | briefing before each campaign map: Führer directives, orders, ally list |
| results | `$02539A–$0280EB` | `$0252DE` (94 words) | 93 distinct (0 = 93) | 23,034 B | `$FF0830` | `$001EC6` | text after each battle, per map and outcome, with news of the war |

Both loops are the same code:

```
lea   <packed>,a0 / lea $FF2000,a4 / bsr $7B98        ; unpack
moveq #0,d0 / move.b <index>,d0 / lsl.w #1,d0
lea   <offsets>,a1 / move.w (a1,d0.w),d0               ; $002324 / $001EB4 (18 bytes)
lea   $FF2000,a0 / adda.w d0,a0
row:  move.b (a0)+,d6                                  ; control byte
      bit 7 → blank row; else d6 & $3F + 1 glyphs, one $00816A call per glyph (typewriter,
      $FF0132 = 9 frames per glyph, A/B/C skip the delay)
      bit 6 → last row: wait for START, done
      7 rows per page (d5), then wait for START and clear; rows 24 px apart ($180 in the buffer)
```

Glyph codes are the normal 16x16 codes (`text.md`), so the extended-glyph escape `FF F0 hh ll`
works here as well.

## LZSS (`$007B98`)

Word = byte budget; flag bytes MSB first, 1 = literal byte, 0 = two-byte reference (12-bit window
position, 4-bit length − 3); 4 KiB window cleared to 0, write position starts at `$FEE`. The
budget is decremented per flag byte, per literal and twice per reference; the loop ends below 0.
`tools/adtext.py` `unpack()` is a port; `tools/adtext.py briefings ROM` prints all entries.

Entries tile the blocks without gaps. Blank rows are used for layout: pushing the ally list or a
quote to the next page, vertical centring.

## Translation (variant tr)

`tools/translate_rom.py` leaves the packed blocks and the unpacking alone (the RAM copy stays
Japanese and unused) and patches the 18 bytes at `$002324` / `$001EB4` to `jsr $1000C0` /
`jsr $1000D0` + 6 × `nop`. The lookup routine does `lea <pointers>,a1 / add.w d0,d0 /
movea.l (a1,d0.w),a0 / rts`: a0 points into an unpacked copy in the ROM (after the 16x16 strings)
with English rows. Long pointers because the English copy is larger than the 32 KiB `adda.w`
allows.

Rows: up to 17 cells (as the JP rows, x = 32–304), word-wrapped from paragraphs; big game font plus
`translation/font/big-extra.txt` (`: ; ! ? " ( ) / &`) and ä ö é è ò drawn in the tool, word space
5 px. Scripts `translation/script/brief-missions.toml`, `brief-results.toml`: per entry `offset`,
`index`, `jp` (checked against the ROM) and `en` items – paragraph, `"^text"` centred row, `""` blank
row, `"<page>"` next page, `"<keep>"` rest of the entry on one page (ally lists, quotes, news). A
paragraph of several rows does not start on the last row of a page.

Cost: 1,541 rows, ~5,900 extended glyphs (identical cells shared); ROM used up to ~`$159000`.

Checked in the game (tr): mission 1 (Case White), both pages, then on to the turn screen.
Checked offline: every page of all 136 entries, rendered from the built ROM through the pointer
tables. **Not seen in play:** the result texts (need a finished battle) – same draw loop and patch.

Pitfall (fixed): the redirect routine is 34 bytes (`$100060–$100081`); a lookup placed at `$100080`
overwrote its `rts` and garbled every string. `translate_rom.py` now asserts the routines do not
overlap.
