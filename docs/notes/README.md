# Notes

One file per topic. Facts only: what the program does and how the port deals with it, with the
evidence in a clause; mark anything unproven as **Hypothesis**. No session history, no
accounts of fixed bugs – only what they taught about the program. Open work goes to the
GitHub issues; `../status.md` says what exists.

| File | Topic |
|---|---|
| `roms.md` | ROM identity, header, JP/EN differences, variants |
| `recompiler.md` | framework, pin, patch stack, Windows support, macOS pitfalls |
| `recompiler-runs.md` | native coverage, interpreter, evidence files, seeding rules |
| `vint.md` | V-int, wait loop, soft reset and the restart mechanism |
| `menu.md` | list engine, title menu, settings screen, Record menu, added rows |
| `campaign.md` | map table, outcomes, dates, unit availability, start year |
| `map.md` | hex map in RAM, drawing, units, overlays, zoomed-out HD map, 16:9 |
| `frame.md` | camouflage frame in the 16:9 margins, armies and countries, battle sides in RAM |
| `graphics.md` | fog of war (shadow/highlight), rain in battles (VDP read-mode writes), Nemesis tiles, intro screens |
| `hd-graphics.md` | HD presentation, tile pack, typeface text, art pipeline |
| `sound.md` | Z80 driver, timers |
| `saving.md` | SRAM, save file, slot format, system menu |
| `phases.md` | whose turn / battle in RAM, automatic fast-forward |
| `controls.md` | keys, pad layout, fast-forward, recording |
| `text.md`, `text-map.md`, `briefings.md` | fonts, encodings, where the text is |
| `translation-rom.md` | how the translated ROM is built |
| `textscan.md` | finding Japanese text on screen |
| `release.md` | the Mac app |
| `windows.md` | Windows build (MSVC + Git Bash), setup on the PC, Windows version for players, unchecked points |
| `work-environment.md` | headless runs, test routes, pitfalls |
