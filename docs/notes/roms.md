# ROMs

Location: `~/RecompProject/_roms/` (outside the repo). Extension `.md` = Mega Drive ROM, not Markdown.

| File | Size | SHA-1 |
|---|---|---|
| Advanced Daisenryaku - Deutsch Dengeki Sakusen (Japan) (Rev A).md | 1 MiB | 842430c0465d810576e75851023929fec873580d |
| Advanced Daisenryaku - english.md (Nebelwurfer patch, partial) | 1 MiB | cdcaf137003e6898e1ac9bf18a8bdc246d108368 |

## Byte diff JP vs. EN (Python comparison)

- 18,321 differing bytes in 110 regions (gaps ≤ 64 bytes merged).
- Largest regions: `$03DD6A–$03F209` (5280 B), `$03F86B–$0409C7` (4445 B),
  `$0EF35B–$0EFF97` (3133 B), `$03D18D–$03DAE6` (2394 B), `$03033D–$030C27` (2283 B).
- Focus `$023000–$041000`. **Hypothesis:** text, font tiles and/or pointer tables.
- `$0EF35B–$0EFF97` near the end of the ROM. **Hypothesis:** free space used by the patch (code or font).

## Header and vector table JP (Rev A)

Evidence: Python read-out of `$000000–$0001FF`.

| Field | Value |
|---|---|
| SHA-256 | 47360b90ee077c2df7bb8f8bb6f46bbea25d7e5b1fd975cdf507c1048d80b062 |
| CRC32 | E0D5E18A |
| System / copyright | `SEGA MEGA DRIVE` / `(C)SEGA 1991.MAR` |
| Title (JP field) | `ADVANCED DAISENRYAKU` (intl field empty) |
| Serial no. / region | `GM 00005505-01` / `J` |
| Checksum | `$D23B` (header = computed) |
| ROM end | `$0FFFFF` (1 MiB, flat, no banks) |
| SRAM | `RA $F8 $20`, `$200001–$20FFFF`, odd bytes only (battery save) |

| Vector | Target |
|---|---|
| SSP | `$FFFFFF00` |
| Entry (reset PC) | `$000224` |
| V-int (level 6) | `$00518C` |
| H-int (level 4) | `$FFFF06` – in RAM, the trampoline is installed at runtime |
| Bus/address error, illegal, ext-int | `$000200` (shared error/dummy handler) |

**Hypothesis:** `$000200` is an endless loop or an `rte` stub; check in the debugger.

## Switchable base

| Variant | SHA-256 | CRC32 |
|---|---|---|
| `jp` | 47360b90ee077c2df7bb8f8bb6f46bbea25d7e5b1fd975cdf507c1048d80b062 | E0D5E18A |
| `en` | 993d7370877838914c9dee4293fa9d7576b5c23af348688dcab488b2c302fac2 | 72C5E589 |

Evidence for "same code": `GenesisRecomp` on both ROMs with the same `game.toml` → 1270 functions,
all generated files identical except for a path comment in `ad_layout.c`.
Selection: `tools/rom_select.sh`, `--rom jp|en` or `ROM_VARIANT` in `config.env`.
