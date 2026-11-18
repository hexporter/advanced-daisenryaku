# Graphics

## Fog of war = shadow/highlight mode

- The map view sets VDP reg 11 = `$02` and reg 12 = `$89` at `$009FFE/$00A006`
  (H40 + shadow/highlight). Another S/H site: `$001A70`. (Evidence: byte search + disassembly)
- The game marks visible hexes and the movement range with **transparent tiles that carry the
  priority bit**: on hardware a tile's priority bit stops the darkening even where its pixel is
  transparent. A VDP model that only counts opaque priority pixels shows the whole map grey.
  The framework has this rule since pin `76490c6`.
- Packing (`fetch_plane_span`): bit 7 = priority (even with nib=0), bit 6 = opaque.

## Rain in battles (framework patch 0015)

- In battle the rain is plane A, priority, palette 2, a 4x4 tile pattern `$651–$660` at VRAM
  `$CA20`; planes A and B share the name table `$E000` (B scrolled down 256). `$FFCDAA` = 2
  gives the rain look (0 = fair; `drive.py` step `P:FFCDAA=02` forces it before an attack).
- Every V-int the game DMAs the 256 words of one animation frame from ROM to `$CA20`, cycling
  `$05CEAC`, `$05D0AC`, `$05D2AC` (raw tiles). Right after the DMA it sets the address `$CA20`
  again with code 0 = **VRAM read** (second control word `$0003`, no DMA bit) and then writes a
  word to the data port – a name-table word such as `$CE76`/`$CE82` (event ring
  `vdp_events`, kind 3 with code 0 at `$CA20`).
- The framework's VDP stored data writes under any read code in VRAM, so the stray word
  replaced the tile's first four pixels and showed as a white/black pixel pair every 32 px.
  Patch 0015 ignores such writes and only advances the address, as Genesis Plus GX does; with
  it `$CA20` holds the ROM words (`0000`/`000F`/`F000`) through the whole battle. **Hypothesis:**
  the real console ignores the write as well (not tested on hardware).

## Tile compression: Nemesis (`$005B1E`)

Evidence: disassembly of `$005B1E–$005C5E`; `tools/nemesis.py` unpacks the intro blocks identical
to the VRAM dumps (credits frame 340, title frame 2000, tr build) and repacks all tested blocks
(10 blocks, 28–1,206 tiles) to within ±1 % of the original size.

- Sega's usual Nemesis format: word header (bit 15 = XOR mode, tile count), code table (`$8x` sets
  the nibble, then count−1/length byte + code; `$FF` ends), bit stream with prefix codes ≤ 8 bits,
  inline run `111111` + 3 bits count−1 + 4 bits nibble. Entry `$005B1E` writes to the VDP data port
  (`$C00000`, target set by the caller), entry `$005B30` to RAM (a4).
- Code table buffer `$FF4400`. Called with `lea <data>,a0` right before the `jsr`/`bsr`.
- Name tables for these screens come separately: `$005C60` unpacks Enigma-style maps to `$FF5000`,
  `$00281E` copies a rectangle into the plane buffer. **Hypothesis** (Enigma), not ported.

### Intro screens (JP, `$000580–$000BC4`)

| Call | Data | VRAM | Content |
|---|---|---|---|
| `$0005AE` | `$0CF980` | tile 0 | first logo screen (48 tiles) |
| `$000646` | `$0D49C8` | tile 0 | 資料提供 / 戦車マガジン / 航空情報 credits (257 tiles; 資料提供 = tiles 75–110, 12×3, row by row, x 112, y 40) |
| `$000B3C` | `$0DB37A` | tile 0 | title background map of Europe (847 tiles) |
| `$000B5E` | `$0DF662` | tile `$357` | "Advanced" plate |
| `$000B74` | `$0DFC84` | tile `$3B7` | 大戦略 logo + subtitle ドイツ電撃作戦 (315 tiles; subtitle = tiles `$4D4–$4F1` as 15 columns of 2 tiles, dashes `$4D1–$4D3` used left and right) |

Layout evidence: test ROM with every tile of both blocks labelled with its number.
