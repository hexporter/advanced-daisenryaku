# Menus

Evidence: disassembly and byte dumps of the JP ROM, RAM dumps and screenshots of the tr build.

## The list engine

Title menu and settings screens share one engine:

- A table of 14-byte records, `$FFFF` ends it: `ID.w` (tile row offset of the row), `Text.l`,
  `Draw.l`, `Action.l`. The screen's routine copies it to `$FFE420`; `$7D5E` resets the cursor,
  `$7D64` / `$7D6A` run the list and return the selection (`$7EC4`: a0 = Action, a1 = Text);
  the caller does `jmp (a0)`.
- `$FFCD38` = cursor row, `$FFCDBC` = number of rows (counted from the table), `$FFCD30` =
  **last row the cursor reaches** (rows beyond it are drawn but out of reach).
- Direction input goes through the `bra.w` table `$007F00` (`recompiler-runs.md`).
- The small menus over the map (Record, yes/no, unit commands) use 10-byte records
  (`ID.w, Text.l, Handler.l`) and `$00F78E`.

## Title menu `$005EAA`

Tables `$005F58` (four rows) and `$005F92` (with a fifth, out of reach: `$0EF14A` → the program
at `$0FA000`); chosen via `d7` after `jsr $0FA018`. Strings are in the 8x8 menu font (`$008104`:
count − 1, then glyph codes; digits 0–9, blank `$14`, A = `$15` …).

| ID | Text | Draw | Action | |
|---|---|---|---|---|
| 0 | `$0EF12F` | `$6026` | `$603C` | CONTINUE |
| 2 | `$0EF141` | `$6026` | `$6088` | CAMPAIGN |
| 4 | `$0EF138` | `$6026` | `$60EA` | STANDARD |
| 6 | `$0EF150` | `$6004` | `$5FDA` | A-MAIN C-SUB (button layout) |

`$6026` = generic draw (highlight when selected, `$8104`). Button layout: `$005F0A` sets
`$FFCDE7` = 1 when SRAM `$20FFF9` = 'A' and `$20FFFB` = 'C'; `$005FDA` toggles it and writes
both bytes (`saving.md`), then `bra $5F50` back into the list.

**Added rows "CAMPAIGN START 1939" and "QUIT GAME"** (tr): inserted as records 4 (ID 8, campaign
start year, `campaign.md`) and 5 (ID 10), later records one row down with their IDs + 2,
`$CD30` = 5; the cursor wraps from QUIT GAME to CONTINUE, the `$0FA000` entry stays out of reach. Text = one of eight strings "CAMPAIGN START 1939" … "1946"
from the translation build (pointer at `$101FF4`, all of one length, which the port reads from
the first length byte; 19 characters end at column 35 of 40), "QUIT GAME" right after them,
Draw = `$6026`, Action = `$5FDA` for both. QUIT GAME pushes SDL's quit event: the runner ends
as when the window is closed (SRAM and evidence written). No 68000 code is added; hooks in `ad_spec.c` (sites in `game.toml`):
at `$005F4C` the row is inserted; at `$005FDA` with a1 = one of our strings the year steps on
and the record's Text is replaced (for QUIT GAME the quit event is sent), and the handler's own effects are undone – `$FFCDE7` is
flipped beforehand (its `eori` restores it) and the two SRAM bytes are put back at its exits
(`$005FF2`, `$006000`). jp/en have no strings and keep four rows.

## System settings screen `$012476` (System menu → System)

Table `$01250A`, copied by `$0124E8`. Draw handler: `jsr $8166` (label, a0 = Text), then the
value string; action handler: change the flag, `bra $0124E2` (redraw).

| Row | Text | Draw / Action | Flag |
|---|---|---|---|
| Battle speed | `$0EF4BD` | `$012544` / `$0125BC` | `$FFCC19` 0–2 (values `$0EF4F3`, 5 bytes each) |
| Hex lines | `$0EF4CB` | `$012562` / `$0125D0` | `$FFCC25` (0 = ON) |
| Enemy unit specs | `$0EF4D5` | `$012580` / `$0125DA` | `$FFCC1D` |
| Pick counter weapon | `$0EF4E3` | `$01259E` / `$0125E4` | `$FFCC1E` |

Box in plane A (`$FF8000`, 128 bytes per row), 30 tiles from column 5: rows 10 (top border) to
22 (bottom border), option rows 11/14/17/20, blank rows between.

**Added row "HD map ON/OFF"** (zoomed-out map, `map.md`): a hook appends a record to the RAM
copy (ID 12, Text = a label from the translation build, pointer at `$101FF0`; the handlers of
row 4) and sets `$CD30` = 4; another moves the box's bottom border to row 25. While row 4's
draw handler runs for our record (a0 = label) the hooks put the zoom state into `$FFCC1E` for
the `tst` and restore it at the `jmp`; in the action handler (a1 = label) the zoom is toggled
and `$FFCC1E` flipped beforehand, so the `eori` restores it. Kept in `ad-port.ini` (`hd_map = on|off`, on by default; F9 stores it too).

**Added row "Language English/Deutsch/Français/Español/Japanese"** (`translation-rom.md`, "Language block"): record 6
(ID 15, the handlers of row 4, `$CD30` = 5), label and the two value strings from the language
block (big typeface, 4 cells; "Japanese" is 63 of the 64 px). The draw handler's hook at `$0125B6` (`jmp $8166`) puts the value string into a0 instead
of ON/OFF; the action hook steps to the next language and draws the title again (`$008166` with the
entry's arguments, registers saved), the list redraws itself. Six rows need the room above:
`$FFCD34` = `07 0B FF 11` is the list's origin (column, row; then the largest ID offsets
drawn), and with the language block the screen sits three tile rows higher – hooks at
`$0124A4` / `$0124C4` move a1 for the boxes and the title, `$FFCD35` = 8, bottom border at row
25. The picture `$0C6D92` copied to `$FF828A` (30x18) holds both boxes: title box from row 5,
title at row 6.

**Added rows "Fast enemy turn ON/OFF" and "Enemy battles 1x/2x/4x/MAX"** (automatic
fast-forward, `controls.md`) as rows 2 and 3, so the screen has eight: Battle speed, the two,
Hex lines, Enemy unit specs, Pick counter weapon, HD map, Language. The RAM table is rebuilt
(game records 1–3 move down, IDs = 3 × row), all added rows use the handlers of row 4 as
above: ON/OFF through `$FFCC1E`, the value of "Enemy battles" put into a0 at `$0125B6`. Labels
and values: six long pointers behind `$101FEC` (`translation-rom.md`). Eight rows fill the
whole screen: after the boxes are copied three rows up, the title box goes to rows 0–3 and the
list's box to rows 3–27 (its top border replaces the title box's bottom border), first row at
4 (`$FFCD35`), last row index 7 (`$FFCD31`). The list draws a row only while its ID is below
`$FFCD37` (`$007FF6`; the screen sets `$11`): 23 for eight rows. Choices kept in `ad-port.ini`.

## Record menu `$0117AA` (System menu → Record)

Table `$011836`: Save `$011AAE`, Load `$0118F2`, Give up `$011860`, Quit `$0118B6`. Quit opens
the dialog `$0118D2` (Cancel `$0118CC`, Exec. `$0118E8`) and leaves for the title menu; Give up
does the same after "You have lost." in standard mode and nothing in the campaign (`$011860`:
`tst.b $FFCC38` / `beq` back into the menu). In the campaign the tr build turns that row into
"Restart" (`campaign.md`, "Restart"). The dialog's title is the string `$0EF250` 中止 ("Cancel"), shared
with six other menus; the tr build points the dialog (`$0118B6`, `lea $0EF250,a1`) at `$0EF253`
中止　, the Quit row's own string, so it reads "Quit" (`tools/translate_rom.py`, QUIT_TITLE). Load and Quit end in stack-reset jumps (`recompiler-runs.md`).

## Other

- V-int mode table and the main menu handlers are seeded in `game.toml` (`extra`).
- Open: what the program at `$0FA000` (title entry 8, alternative V-int when `$FF0040` ≠ 0)
  does; the shared handler `$000200`.
