# Controls of the port

| Input | Effect | Source |
|---|---|---|
| Right trigger (controller 1) | fast-forward, continuous 1×–128× (quadratic: half press ≈ 32×) | patch 0004 |
| — (automatic) | fast-forward during enemy turns, battles at normal speed | patch 0005 + `ad_spec.c` |
| Hold Tab or Back/View | turbo: frame pacing lifted, sound off | runner |
| Esc / close window / Cmd+Q | quit normally (save game + evidence are written) | runner |
| F7 or Back + RB | quick-save selection | runner |
| F8 or Back + right stick | rewind | runner |
| F9 | zoomed-out HD map on/off (also System menu → System → "HD map") | `ad_mapzoom.c`, `map.md` |
| F10 | HD graphics / original pixels | patch 0007, `hd-graphics.md` |
| Left stick click (L3), any pad | start/stop a video of the HD frame; red dot top right while recording | `ad_record.c` |
| `0`–`3` (only with `run.sh --ramlog`) | mark the game phase for the RAM recording | `phases.md` |

In-game choices added by the port: title menu rows "CAMPAIGN START 1939" (campaign start year,
`campaign.md`) and "QUIT GAME" (ends the game, `menu.md`), System settings row "HD map" (`menu.md`).

## Video recording (`recomp/game/ad_record.c`)

L3 starts and stops (`AD_REC=1 tools/run.sh` starts with the first HD frame, for tests); needs
the HD frame on and ffmpeg (encoder `h264_videotoolbox` on the Mac, `libx264` on Windows,
`AD_REC_CODEC=…` chooses another); stops by itself after 10 minutes. Files in `build/video/` (not in
the repo); in the Mac app and the Windows release (`GENESIS_USER_DIR` set) in `video/` of the
data folder.

Each frame goes to ffmpeg's pipe as one packed write (5.7 MB at 1592x896, the pipe
unbuffered). Row by row through the C runtime's 4 KiB buffer it was ~1400 pipe writes per
frame, and on Windows the game ran at ~32 fps while recording; now 900 frames take 18.0 s
recording, 17.8 s without (Ryzen 7600X3D; `libx264 -preset veryfast` alone encodes this frame
size at ~600 fps). **Hypothesis** (not tried): without ffmpeg a start ends at once with
"[REC] ffmpeg stopped accepting frames".

- `rec-<time>.mp4` – the HD frame (1592x896 with the 16:9 margins, else 1280x896), only
  presented frames, ~225 MB/min;
- `.csv` – per video frame: `$CD14`–`$CD21`, cursor object x, what the zoomed map used for
  that frame, pad, view used for the sprites;
- `.bin` – per video frame `$1BC0` bytes: units `$FFB000` `$1800`, sprite table `$280` (only
  while the zoomed map is active), `$FFCD00` `$100`, `$FFD1C0` `$40`.

Video frame n is csv line n+2 and bin record n, so a bug seen in the video can be read off
exactly.

## Controller layout (Xbox pad)

| Xbox | Genesis | Runner default |
|---|---|---|
| A | B | B |
| X | **A** | C |
| B | **C** | A |
| Y | X (6-button only) | X |

X and B are swapped against the runner default. The runner reads the bindings from
`settings.ini` next to `ADRecomp` (`runner/app_config.c`, section `[input.p1]`,
`pad.<Genesis> = button:<SDL number>`). Project file `recomp/game/settings.ini`;
`tools/build.sh` copies it into the build folder only when none is there, and `--clean` keeps
it, so a layout changed in the launcher or in-game menu stays. Deleting the `pad.` lines in
`build/recomp-<variant>/settings.ini` restores the runner default.

## Fast-forward (patch 0004)

- Every game frame is still computed; only every n-th is displayed. Frame pacing keeps 60
  displayed frames/s, so the game runs n times as fast. Sound off while > 1.05×.
- Dead zone ~6 % of trigger travel. Maximum 128× (8× is too slow for the computer's thinking
  late in a game); `GENESIS_FF_MAX=16 tools/run.sh` lowers it. The real limit is CPU power.
- No effect in netplay and with `--measure-runtime`.
- The turbo (Tab/Back) is limited by VSync and hardly faster than normal; fast-forward avoids
  that by skipping frames.

## Automatic fast-forward during enemy turns (patch 0005 + `ad_spec.c`)

On by default: enemy turns run at 128×, battle animations at normal speed. System menu →
System: "Fast enemy turn" ON/OFF switches it, "Enemy battles" sets the speed of the battle
animations during the computer's turn – 1x, 2x, 4x or MAX (= the fast-forward factor); the
player's own battles stay at normal speed. Above 1× there is no sound (patch 0004), so faster
enemy battles run silent. Both choices are kept in `ad-port.ini` (`fast_enemy_turn = on|off`,
`enemy_battles = 1x|2x|4x|max`, `menu.md`). A lower speed takes effect at once, a higher one
after it has been asked for 8 V-ints in a row (the battle state leaves its values for single
frames, `frame.md`). `AD_AUTO_FF=0` switches it off for one launch without touching the stored
choice, `AD_AUTO_FF=32` selects 32×; `AD_FF_LOG=1` logs every change of speed. The right
trigger still works (the faster of the two wins). Off while the system menu is open
(`saving.md`). Detection: `phases.md`.
