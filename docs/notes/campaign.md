# Campaign: map table, outcomes, great victory

Evidence: disassembly (JP Rev A), headless runs of the tr build (RAM dumps, turn screens).

## Mode and map

- `$FFCC38`: 0 = campaign (cleared by the CAMPAIGN handler `$006088`), 1 = standard
  (`$0060EA`). RAM dumps: campaign 0, standard scenario 0 → 1.
- `$FFCC37`: campaign map number (0–43; `$FF` in standard mode).
- `$006488` loads map `$CC37`: record `$07EF28 + $70 · map` (112 bytes; the standard-mode record
  is the one before, `$07EEB8`). The names in it are the scenario names
  (`translation/script/names-scenarios.toml`, same order).

| Record byte | RAM | Meaning |
|---|---|---|
| `$00–$07` | `$FFCC00` | map name (8 glyphs) |
| `$09–$0B` | `$FFCC14–16` | start date year (− 1900) / month / day – used as is only on the first map ($CDC3 set); later maps continue from the current date (below) |
| `$0C` | `$FFCC18` | turns until END (draw) |
| `$0D` | `$FFCC2F` | **great-victory turns** |
| `$13`/`$14` | `$FFCC30`/`31` | great victory: result text / next map |
| `$15`/`$16` | `$FFCC32`/`33` | victory: result text / next map |
| `$17`/`$18` | `$FFCC34`/`35` | draw (END reached): result text / next map |

Result text = entry of the results block (`briefings.md`, index `$FF0830`, set by `$001D3E`).
Next map 43 (`$2B`) ends the campaign (`$008D36` → `$00151E`, d0 = 1).

## Restart (Record menu, tr build)

`recomp/game/ad_restart.c`. In the campaign the Record menu's third row reads "Restart"
(de "Neustart", fr "Rejouer", es "Reiniciar") instead of the "Give up" that does nothing there;
it opens the game's own Cancel / Exec. dialog with "Restart" as title, and Exec. begins the map
in play again. Standard mode keeps "Give up".

- Every map starts at `$0085D4` (new game `$0063B4`/`$0063BC`, next map `$008D52`). There the
  port copies the six RAM blocks a save holds (`saving.md`); Restart puts them back, clears the
  shown weather `$FFCDAA`/`$FFCDAB` (as the loader `$006510` does) and re-enters `$0085D4` with
  the game's stack `$FFCDA6`. Evidence: headless runs en/de/fr/es – after a day and a Restart
  the six blocks on the map equal those of the map's first turn byte for byte; date, money and
  weather of day 1 are back.
- Loading the map a second time is no way: the loader `$006488` keeps the player's units, adds
  money and moves the date on.
- No 68000 code is added: hooks swap the row's text pointer in table `$011836` (`$01184C`), let
  the handler `$011860` see `$FFCC38` = 1 for its one test, set the dialog title (`$011876`) and
  take over Exec. (`$01189E`). The two strings sit behind the pointer `$101FFC`
  (`translation-rom.md`).
- A save keeps its map start: Save copies the snapshot into a companion record of the slot,
  Load takes it back when the slot's six checksums match (`saving.md`, "Map start"). A save
  without one (made before, or from an emulator) has no map start: the row stays "Give up" until
  the next map begins.
- jp/en builds have no strings and no row.

## One turn = one day

The turn loop `$0085D4` hands the turn to the next army (`$008C1A`); after the last army the day
changes (`$008D5E`):

```
subq.b #1,$CC18 / bne → else outcome 2 (draw), next map $CC35
tst.b $CC2F / beq / subq.b #1,$CC2F         ; great-victory counter, stops at 0
... date + 1 day ($008CDC), income
```

Day 1 has no day change, so on day k the counter is `$0D − (k − 1)`. Checked: Case White day 1
`$CC2F` = 15, `$CC18` = 25; after one turn (day 2) 14 and 24.

## Victory: great or normal (`$00B6C4`)

On victory (`$00B80A` true): `$CC2F` ≠ 0 → outcome 0 (great victory, text `$CC30`, next `$CC31`),
else outcome 1 (victory, `$CC32`/`$CC33`). So **a win is a great victory up to and including the
date today + `$CC2F` − 1** – the same formula the game uses for END (`$008B86`: today +
`$CC18` − 1). Case White: start 39.9.1, great victory up to 39.9.15, END 39.9.25.

Start dates are dynamic in a campaign: `$006832` continues from the current date, adding a day
(and income) until the record's date is reached – at least one day. The counter always starts at
`$0D` on the map's first day, so the great-victory date moves with the start date.

**Secret ending** (`$00B6DA`): a great victory on map 11 (SeaLion), 21 (Caucasus) or 32
(FrAfrica) adds 1 to `$FFCC39`; a great victory on map 31 (Turk.War) sets it to 3. At 3 the
game jumps to `$00151E` with d0 = 0 instead of the next map (epilogue and credits). Seen in
play after a great victory in FrAfrica. The counter is cleared by the CAMPAIGN handler.

## Shown on the turn screen (tr build)

The turn screen `$008B1A` draws NOW (row 15) and END (row 18) in the 16x16 font. `translate_rom.py`
(`apply_victory_date`) moves END to row 21 and puts a line "GREAT <date>" on row 18: routine at
`$101F00`, called from `$008BB8`; only when `$CC38` = 0 and `$CC2F` > 0. Checked in the game:
day 1 and day 2 of Case White show GREAT 39. 9.15 between NOW and END (1x and HD); standard mode
shows no line (END one line lower).

## Map table

Values from the JP ROM (`$0C`/`$0D` in turns = days).

| # | Record | Map | Start (table) | END turns `$0C` | Great turns `$0D` | Great victory: text/next | Victory: text/next | Draw: text/next |
|---|---|---|---|---|---|---|---|---|
| 0 | `$07EF28` | Case Wht | 39.9.1 | 25 | 15 | 1/2 | 2/1 | 3/0 |
| 1 | `$07EF98` | Piotrkow | 39.9.11 | 30 | 15 | 4/3 | 5/2 | 3/1 |
| 2 | `$07F008` | RadomPkt | 39.9.11 | 30 | 15 | 6/4 | 7/3 | 3/2 |
| 3 | `$07F078` | Vistula | 39.9.15 | 50 | 20 | 8/4 | 8/4 | 3/3 |
| 4 | `$07F0E8` | Warsaw | 39.9.20 | 50 | 25 | 9/6 | 9/5 | 3/4 |
| 5 | `$07F158` | Denmark | 40.4.9 | 30 | 10 | 10/6 | 11/7 | 3/5 |
| 6 | `$07F1C8` | Norway | 40.4.9 | 60 | 30 | 12/7 | 13/8 | 3/6 |
| 7 | `$07F238` | Benelux | 40.5.10 | 60 | 30 | 14/9 | 15/8 | 3/7 |
| 8 | `$07F2A8` | Somme | 40.6.5 | 70 | 50 | 16/12 | 17/25 | 3/8 |
| 9 | `$07F318` | Maginot | 40.6.5 | 50 | 30 | 18/10 | 19/14 | 20/25 |
| 10 | `$07F388` | BtlBritn | 40.7.10 | 60 | 30 | 21/11 | 22/12 | 23/13 |
| 11 | `$07F3F8` | SeaLion | 40.9.19 | 70 | 40 | 24/14 | 25/12 | 26/13 |
| 12 | `$07F468` | Yugoslav | 41.4.6 | 35 | 20 | 27/15 | 28/13 | 3/12 |
| 13 | `$07F4D8` | Greece | 41.4.6 | 55 | 40 | 29/16 | 30/26 | 3/13 |
| 14 | `$07F548` | Baltics | 41.6.22 | 100 | 40 | 31/17 | 31/17 | 3/14 |
| 15 | `$07F5B8` | Smolensk | 41.6.22 | 110 | 50 | 32/18 | 32/18 | 3/15 |
| 16 | `$07F628` | Ukraine | 41.6.22 | 100 | 40 | 33/19 | 33/19 | 3/16 |
| 17 | `$07F698` | Moscow4P | 41.10.2 | 70 | 45 | 34/36 | 35/21 | 36/20 |
| 18 | `$07F708` | Moscow2P | 41.10.2 | 70 | 45 | 34/36 | 35/21 | 36/20 |
| 19 | `$07F778` | Rostov | 41.9.10 | 100 | 50 | 37/18 | 38/20 | 3/19 |
| 20 | `$07F7E8` | Sevastop | 42.5.8 | 70 | 30 | 39/21 | 40/22 | 3/20 |
| 21 | `$07F858` | Caucasus | 42.6.28 | 120 | 65 | 41/32 | 42/22 | 43/22 |
| 22 | `$07F8C8` | Stalingr | 42.11.19 | 70 | 40 | 44/23 | 44/23 | 45/23 |
| 23 | `$07F938` | Kharkov | 42.12.16 | 110 | 50 | 46/24 | 46/24 | 47/34 |
| 24 | `$07F9A8` | Kursk | 43.7.5 | 45 | 30 | 48/33 | 49/34 | 50/35 |
| 25 | `$07FA18` | Cyrenai. | 41.2.12 | 70 | 35 | 51/27 | 52/26 | 3/25 |
| 26 | `$07FA88` | Tobruk | 42.1.21 | 70 | 40 | 53/29 | 53/29 | 3/26 |
| 27 | `$07FAF8` | EgyptSyr | 41.4.11 | 60 | 35 | 54/28 | 54/28 | 55/26 |
| 28 | `$07FB68` | IranIraq | 41.6.22 | 80 | 45 | 56/31 | 57/26 | 58/26 |
| 29 | `$07FBD8` | Alamein | 42.6.23 | 50 | 35 | 59/30 | 60/32 | 61/32 |
| 30 | `$07FC48` | NearEast | 42.7.23 | 70 | 50 | 62/31 | 62/31 | 63/32 |
| 31 | `$07FCB8` | Turk.War | 42.7.23 | 80 | 45 | 64/32 | 65/22 | 66/23 |
| 32 | `$07FD28` | FrAfrica | 42.11.8 | 90 | 50 | 67/23 | 68/33 | 69/33 |
| 33 | `$07FD98` | Sicily | 43.7.9 | 55 | 30 | 70/37 | 71/34 | 72/34 |
| 34 | `$07FE08` | Salerno | 43.9.3 | 80 | 55 | 73/37 | 74/35 | 75/35 |
| 35 | `$07FE78` | Anzio | 44.1.22 | 80 | 60 | 76/37 | 76/38 | 77/38 |
| 36 | `$07FEE8` | Ural | 41.12.1 | 80 | 50 | 78/21 | 79/20 | 80/20 |
| 37 | `$07FF58` | Normandy | 44.6.6 | 55 | 35 | 81/39 | 81/39 | 82/38 |
| 38 | `$07FFC8` | Falaise | 44.8.15 | 60 | 35 | 83/41 | 83/41 | 84/39 |
| 39 | `$080038` | Arnhem | 44.9.17 | 40 | 25 | 85/40 | 85/40 | 86/42 |
| 40 | `$0800A8` | Ardenn44 | 44.12.16 | 60 | 40 | 87/41 | 87/41 | 88/42 |
| 41 | `$080118` | Budapest | 45.1.1 | 50 | 30 | 89/42 | 89/42 | 90/42 |
| 42 | `$080188` | Germany | 45.2.1 | 50 | 30 | 91/43 | 91/43 | 92/43 |
| 43 | `$0801F8` | IslandCp | 42.1.1 | 200 | 100 | 1/3 | 2/2 | 3/1 |

## Unit availability by date

- **Table `$0280EC`: 690 records of 12 bytes**, one per unit entry. `+4`/`+5` = year (− 1900) /
  month from which the entry is on offer; **Hypothesis:** `+2` word = price (5000, 1500, 1000 …),
  `+6` a flag used by `$009868`. Intro years: up to 1938 147 entries, 1939 38, 1940 48, 1941 77,
  1942 115, 1943 114, 1944 100, 1945 50 (latest 45.9), one entry year 99 (never).
- `$00982C` (called from `$0063B8`, `$008742`): clears the list at `$FFCA00` (46 longwords, one
  bit per entry, set by `$009A28`) and marks every entry whose year/month is **before** the
  current one (`move.w $CC14,d6 / cmp.w 4(a6),d6`, equal does not count).
- `$00944A` (daily development): an entry at or past its date is added on a random day of
  the month (`$FF0020` mod the days left to the 29th).
- The date only moves forward: `$008CDC` adds a day (month lengths, year + 1, no upper limit
  seen); `$006868` (later maps) adds days until the date is at or past the map record's date,
  comparing year, then month, then day – with a later current date exactly one day.

## Chosen start date

Only the first map takes its record's date, and the units on offer follow the date alone, so
a later start date gives later units for the whole campaign (the balance is gone: the
computer builds too, but e.g. Poland has no late-war units).

- **Title menu row "CAMPAIGN START 1939"** (tr build; `menu.md`): A steps through 1939 … 1946 and back.
  1939 = the game's own date (39.9.1), every other year = 1 January of that year; from 1946
  every entry is on offer (689; one entry has year 99). Holds for every CAMPAIGN start, is kept
  between launches (`ad-port.ini`: `campaign_start = 1939..1946`) and does not affect standard
  scenarios.
- `AD_CAMPAIGN_START=YY.M.D` sets an exact date (e.g. `45.4.30`: 657 entries on offer); it
  applies while the row says 1939.
- How: hooks at `$0064B8` / `$00650E` in the map loader `$006488` replace the date when
  `$FFCC38` = 0 (campaign) and `$FFCDC3` is set (first map) – `ad_spec.c`.
- Turn counters are unchanged (Case White 25 / 15), only the calendar moves; season and
  weather follow the month. Played over four maps from 45.4.30: dates continue, save and load
  work. Not tested: a long campaign from 1946, year changes after it.
