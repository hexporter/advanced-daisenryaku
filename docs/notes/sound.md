# Sound

Evidence: disassembly (68000 and Z80) of JP Rev A, runner sources.

## Structure

- The 68000 never accesses the YM2612 directly (no accesses to `$A04000–$A04002`).
  PSG from the 68000 only at `$002B56–$002B9E` (muting).
- The Z80 driver (SMPS-like) is loaded at `$0003F2`:
  - `$0C3E78`, `$1115` bytes → Z80 `$0000` (code)
  - `$0C4F8C`, `$819` bytes → Z80 `$1200` (**Hypothesis:** effect data)
  - `$000534`, 13 bytes → Z80 `$1C00` (initial values: `0C 00 00 80 B4 00 E6 80 00 00 00 00 00`)
  - second variant `$000478`: `$0C57A4`, `$161` bytes → `$0000`, `$000542` → `$1FF8`
- Sound command: `$008564` writes `d0` to Z80 `$1C0A` (with BUSREQ).
- Bank register: Z80 `$0710` writes 9 bits from `$1C00/$1C01` to `$6000`.

## Z80 main loop `$006F`

Waits for `$1C07` ≠ 0, then YM status (`ld a,($4000)`):
- `$1C07` negative (initial value `$80`): timer B (bit 1) → `$00D3`, `$0723`, `$050A`, `$010F`
  (channels from `$1E80`); timer A (bit 0) → `$00B9`, `$00E5` (among others channels from `$1C40`, `$1C70`).
  **Music runs on timer A, effects on timer B.**
- `$1C07` positive: only timer B, `$00E5`.
- Timer A: `$00B9` from `$1C04/05` (= `$00B4` → N = 180 → (1024−180)·144/fM ≈ 15.8 ms).
  Timer B: `$00D3` from `$1C06` (= `$E6` → (256−230)·16·144/fM ≈ 7.8 ms).
  `$27` is written on every service with both load bits (`$1F`/`$2F` | `$1C12`).

## What the runner needs (framework patch 0003)

The driver needs both YM timers: timer A (`$24/$25`, clock 144·7 master cycles) and timer B,
each restarting only on its load bit going 0→1 – the driver writes `$27` with both load bits on
every service, so a restart on every write would keep resetting the slower timer A. Without
timer A the effects play but the music never does.

Because the music is driven by the Z80 and the YM timers, fast-forward carries it along
(`controls.md`).

## Commands and priorities

Evidence: Z80 disassembly, Z80 RAM dumps through the debug server (`tools/drive.py` `Z:`),
the command log (`AD_SND_LOG=1`).

- The 68000 writes every command to `$1C0A` only. The Z80 reads `$1C0A`–`$1C0C` at `$0883`
  (called on every pass of the main loop) and clears each slot it reads, taken or not.
- A command is taken only when its priority is higher than the one playing, `$1C18`
  (`$0891`: `cp (hl)` with the table entry; taken → `$1C09` = the command, `$1C18` = its
  priority & `$7F`). Priority table: pointer at the start of the bank (`$1C00/$1C01` = `$0C`
  → ROM `$0C0000`, window `$8000`), table at ROM `$0C0272`, one byte per command from `$81`:
  music `$81`–`$8F` = `$80` (0), effects `$90`–`$BF` = `$90` (`$10`), `$E1` = 3.
- `$050A` runs the taken command: `$81`–`$8F` music, `$90`–`$B6` effects, `$E0`–`$F8`
  through the table at `$0531`. `$E1` → `$07EB`: clears `$1C09`–`$1F9F` and silences every
  channel (stop all). The title menu sends it on entry (`$005EAE`); also `$00B756`, `$011FF2`.
- `$1C18` goes back to 0 with every `$E0`+ command (`$052D`) and at `$0F8B` while `$1C19` ≠ 0;
  with the system menu open `$1C19` = `$80`.
- Clicks of the menus: `$AB` (cursor, `$007EC0`), `$AC` (back, `$007EF8`), `$AD` (`$007F72`).

### Lost commands (port)

On a console the Z80 reads `$1C0A` within microseconds; in the port it runs once per scanline
after the 68000's share, so two commands written in one share leave only the second. Seen in
the command log: Record → Quit → Exec. writes the click `$AB` and the stop `$E1` in one share
(the click is lost, harmless). `ad_spec.c` keeps the stop from being lost: before `$E1` it
clears `$1C18`, and an effect never replaces an unread stop or music command (the effect is
dropped, logged as "dropped"). Every `$E1` writes a line to `run.log` with the slot and
priority it met.

Open: now and then a map's music keeps playing in the title menu after Quit, until the title
menu is entered again. The stop is not lost on the way: in every logged Quit it met the slot
holding only the click `$AB`, priority 0, and nothing was dropped – what keeps or restarts the
music after the Z80 has the stop is not known yet (not reproduced headless).

