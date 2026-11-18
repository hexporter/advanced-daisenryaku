# Status

What the port does as of 18.11.2026. Details are in `notes/` (index: `notes/README.md`).

## What exists

- **Native Mac port** (arm64) of Advanced Daisenryaku via segagenesisrecomp, pin `76490c6`
  with patches 0002–0015. Everything is playable: intro, campaign to its endings, standard
  mode, battles, fog of war, saving/loading, music and effects.
- **Fully native in play:** 1666 functions (tr); a play session interprets nothing. The
  interpreter stays on as the safety net; the fold cycle `build.sh → run.sh → fold.sh` picks up
  anything new (`recompiler-runs.md`).
- **ROM variants** jp / en (Nebelwurfer patch) / tr (our translation), identical code; tr is
  generated from jp (`translation-rom.md`). Development happens in tr.
- **English translation complete:** menus, commands, errors, names (8 characters), campaign
  briefings and result texts, intro captions and graphics, epilogue. Not translated: the 大戦略
  logo and the magazine logos.
- **Language switch** (tr): System menu → System → "Language" steps through English, Deutsch,
  Français, Español and the original Japanese, at once and without a restart; the choice is kept between
  launches. Until one is chosen, the system language decides (else English)
  (`translation-rom.md`, "Language block").
- **German, French and Spanish translations complete** (`translation/de`, `fr`, `es`, from the
  English): menus, commands, errors, names, intro captions, briefings and result texts,
  epilogue; not reviewed by a reader (`translation/glossary-<code>.md` list the choices).
  The tr ROM is 3 MiB for that (`translation-rom.md`, "Layout").
- **HD presentation** (F10): every line rendered again at 4x; all text set with Nunito Sans;
  art pipeline ready, no redrawn art (`hd-graphics.md`).
- **Zoomed-out HD map** (on by default, kept between launches; F9 or System menu → System → "HD map"): half-size
  hexes, own camera, **16:9** frame with the map across the full width (`map.md`).
- **Camouflage frame** in the 16:9 margins of every other screen: the pattern of the country
  in play, in battles the two countries fighting; `AD_FRAME=0` = black margins (`frame.md`).
- **Comfort:** fast-forward on the right trigger, automatic fast-forward during enemy turns
  (System menu → System: "Fast enemy turn" on/off, "Enemy battles" 1x/2x/4x/MAX, kept between launches),
  video recording with per-frame data (L3), save converter for emulator saves (`controls.md`,
  `saving.md`).
- **Campaign extras (tr):** "GREAT <date>" line on the turn screen (last day for a great
  victory); title menu row "CAMPAIGN START 1939" to begin the campaign in a later year with later units
  (kept between launches);
  Record menu row "Restart" begins the map in play again from its start, without a save slot
  (`campaign.md`).
- **Windows port (x64):** MSVC + Git Bash, `tools\win build|run --rom tr`; builds and plays on
  Windows 11: everything checked in play (nothing interpreted, Load / Quit / Restart / soft
  reset, HD, zoomed map, pad, fast-forward, sound; sharp under display scaling). Windows version
  for players by `tools\win release_windows` (folder with `Advanced Daisenryaku.exe`, data in
  `%APPDATA%`, 16:9 with the HD pack, launcher icon 大): built, smoke test passed, played from
  the unpacked zip (SmartScreen, ROM dialog, wrong file, save/load, ROM moved). The tr ROM and the
  HD pack come from the Mac. On the Mac `tools/wincheck.sh` cross-builds it with mingw-w64
  (`windows.md`).
- **Mac app:** `tools/release.sh` builds `build/release/Advanced Daisenryaku.app`; the player
  supplies the JP ROM, the app patches it (`release.md`).

## Next steps and open questions

Tracked as GitHub issues (labels `needs-playtest`, `translation`, `mac`, `windows`, `recomp`,
`hd`, `research`; milestone v0.1.0 = first public release).
