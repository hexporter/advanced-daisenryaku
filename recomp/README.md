# Recomp

| File | Contents |
|---|---|
| `CMakeLists.txt` | Game build: generates C from ROM + `game/game.toml`, links the segagenesisrecomp runner |
| `game/game.toml` | Recompiler config: seeds, RAM layout, jump tables, hook sites |
| `game/ad_spec.c` | GameSpec: entry point, interrupts, ROM identity, game hooks |
| `RECOMPILER_COMMIT` | pinned recompiler revision (`tools/recompiler_update.sh`) |

Build and run: `tools/build.sh`, `tools/run.sh` (see `tools/README.md`).
Generated C code goes to `build/recomp-<variant>/generated/ad/` and is not committed.
`game/ad-jp.bin`, `game/ad-en.bin` are symlinks to the ROMs (created by `tools/build.sh`, not committed).
`patches/` holds our own fixes to the framework (see `docs/notes/recompiler.md`).
