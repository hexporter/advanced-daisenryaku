# Saving (battery SRAM)

Evidence: disassembly, byte search, save files checked against the layout below.

- Header: `RA $F8 $20`, `$200001–$20FFFF` (odd bytes), ROM end `$0FFFFF` (`roms.md`). The game
  uses the whole range and never touches `$A130F1`/`$A130F0`, so the runner must provide 64 KiB
  and map SRAM whenever its base lies above the ROM end (framework patch 0002 for the buffer;
  the mapping is upstream). The tr ROM (3 MiB) lies over that range; there the runner shows the
  RAM only while bit 0 of `$A130F1` is set, so the port writes 1 to it before the game starts
  (`ad_call_entry_point`). Evidence: tr boots with the cursor on CONTINUE and writes its `.srm`.
- `$20FFF9`/`$20FFFB` hold the **button layout**, not a signature: `$005F0A` sets `$FFCDE7` = 1
  for 'A','C'; `$005FDA` toggles it and writes 'C','A' or 'A','C'; `$00600E` then shows
  `$0EF15E` Ａ―ＳＵＢ　Ｃ―ＭＡＩＮ instead of `$0EF150` Ａ―ＭＡＩＮ　Ｃ―ＳＵＢ. `$FF` = default.
- `gbus_init`: version register `$A10000` = `$80` (overseas, NTSC); the Japan-only game starts
  anyway, no region check seen.

## Save file

- `build/recomp-<variant>/<ROM basename>.srm`, 65,536 bytes raw (even bytes unused).
  `build.sh --clean` keeps `*.srm` and `native_save_*.bin`.
- Emulators store either the 32 KiB of odd bytes or the 64 KiB range; a Genesis Plus GX style
  file has the data on the odd bytes, `$FF` on the even ones and the trailing `$FF` cut off.
- `tools/srm_convert.py`: `to-emu` (32 KiB odd bytes, `--full` 64 KiB), `to-port` (32 KiB or up
  to 64 KiB, also trimmed files), `names` (below). An emulator save converted with `to-port`
  loads in the port; `to-emu --full` gives the original bytes back.

## Slot format and checksums

Offsets in the 32 KiB of data (odd bytes). Three slots at `$0001 + k × $2A80`.

- Load: `$0118F2` → `$011DC6` (slot choice, a0 = slot) → `$011BE8` compares 64 bytes at
  a0 + `$5400` (bus; data `+$2A00`) with the signature at `$011C1A` (`SEGA MEGA DRIVE (C)SEGA
  1990.AUGSUPER DAISENRYAK      BACKUP RAM`) → `$0119AA` copies six blocks back to back and
  compares each block's 32-bit byte sum with a big-endian long read by `$011BB4` (after the
  signature, data `+$2A40`).
- Blocks: `$100` → `$FFCC00`, `$1000` → `$FFA000`, `$1400` → `$FFB000` (256 × 18 + 2 bytes,
  4 RAM bytes skipped per record), `$200` → `$FFC800`, `$200` → `$FF4000`, `$100` → `$FFCA00`.
- A sum mismatch shows "Save data is corrupted. / Please press the reset button." (`$0EFF68`,
  `$0EFF7F`, drawn at `$011972`) and stops.

**Names in the save:** saving copies 8-character names into the slot – the scenario name at
slot `+$04` (block `$FFCC00`) and the army names (slot `+$2510`, `+$2530`, `+$2590`, `+$25B0`,
…). A save made with another ROM keeps that ROM's names (an EN-patch save shows "Germany" in
the tr build). `tools/srm_convert.py names` replaces them by the target ROM's names at the same
table index and recomputes the sums. In the tr build the port renames these copies in RAM to
the language chosen (`translation-rom.md`, "Language block"), so a save follows the language
it is loaded in.

## Map start (tr build)

`ad-mapstart.bin` in the data folder (`GENESIS_USER_DIR`, else the working directory = the
build folder): magic `ADMAPST1`, then three records, one per slot, of `$2E1C` bytes – valid,
map number, 2 bytes padding, the slot's 24 checksum bytes (`$5480`, odd bytes) as key, and the
six save blocks as they were when that map began. Written on every Save, read on Load
(`campaign.md`, "Restart"). Not part of the save file: a converted or copied `.srm` has no
map start.

## System menu and Record menu

- System menu (Record, Sound, Control, Fog, Weather, System): table `$01016A`, routine
  `$0100CA`, handlers called by `jsr (a0)` at `$01014A`. During the computer's turn A/B/C opens
  it (`$00C6CE`, back at `$00C6FA`).
- The automatic fast-forward is off while it is open (hooks `$0100CA` / `$00C6FA`): at 128× the
  menu is unusable. Framework patch 0006 makes the interpreter guard count per frame, so code
  that waits for V-ints in a capsule cannot trip it.
- Record menu `$0117AA`–`$011E2C`: `menu.md`. Save `$011AAE`, yes/no `$011DC6`, row callback
  `$011D22`; all native. Load and Quit end in stack-reset jumps (`recompiler-runs.md`).
- Test routes through the Record menu can write the save file (`work-environment.md`).
