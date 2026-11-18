# Shared ROM selection for build.sh, run.sh, recompiler_update.sh (sourced via ".").
# Variants: jp = original (Japan Rev A), en = Nebelwurfer patch (changes only data, no code;
# docs/notes/text.md), tr = our translation, generated from jp by tools/translate_rom.py
# (3 MiB, small code patch; docs/notes/translation-rom.md). Separate build folders and save games.
#
#   rom_select <jp|en|tr>   sets ROM_VARIANT, ROM_FILE, ROM_SHA256, ROM_CRC32, ROM_SIZE, ROM_BUILD
#   (tr: ROM_SHA256/ROM_CRC32 empty, the ROM is generated; rom_crc32 computes the CRC)
#   Default: ROM_VARIANT from config.env, otherwise jp.

# Windows (Git Bash, docs/notes/windows.md): ROOT as C:/… so that native programs (cmake, the game)
# and the CMake cache see one spelling; executables end in .exe; Python is "python" there
# (python3 may be the Microsoft Store stub).
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) AD_WINDOWS=1; EXE=.exe; ROOT=$(cd "$ROOT" && pwd -W) ;;
    *)                    AD_WINDOWS=0; EXE="" ;;
esac
if [ -z "${PYTHON:-}" ]; then
    if python3 -c '' 2>/dev/null; then PYTHON=python3; else PYTHON=python; fi
fi

rom_select() {
    ROM_VARIANT=${1:-${ROM_VARIANT:-jp}}
    case "$ROM_VARIANT" in
        jp) ROM_FILE=${ROM_JP_PATH:-${ROM_PATH:-}}
            ROM_SHA256=47360b90ee077c2df7bb8f8bb6f46bbea25d7e5b1fd975cdf507c1048d80b062
            ROM_CRC32=E0D5E18A; ROM_SIZE=0x100000 ;;
        en) ROM_FILE=${ROM_EN_PATH:-}
            ROM_SHA256=993d7370877838914c9dee4293fa9d7576b5c23af348688dcab488b2c302fac2
            ROM_CRC32=72C5E589; ROM_SIZE=0x100000 ;;
        tr) ROM_FILE="$ROOT/build/rom/ad-tr.md"
            ROM_SHA256=""; ROM_CRC32=""; ROM_SIZE=0x300000 ;;
        *)  echo "Unknown ROM variant '$ROM_VARIANT' (jp|en|tr)"; return 1 ;;
    esac
    [ -n "$ROM_FILE" ] || { echo "Path for ROM variant '$ROM_VARIANT' missing in config.env"; return 1; }
    ROM_BUILD="$ROOT/build/recomp-$ROM_VARIANT"
}

rom_verify() {
    [ -f "$ROM_FILE" ] || { echo "ROM not found: $ROM_FILE"; return 1; }
    [ -n "$ROM_SHA256" ] || return 0   # tr: generated, its JP base is checked by translate_rom.py
    local sha
    if command -v shasum >/dev/null; then sha=$(shasum -a 256 "$ROM_FILE" | cut -d' ' -f1)
    else sha=$(sha256sum "$ROM_FILE" | cut -d' ' -f1); fi
    [ "$sha" = "$ROM_SHA256" ] ||
        { echo "Wrong ROM for variant '$ROM_VARIANT' (SHA-256 $sha): $ROM_FILE"; return 1; }
}

# CRC32 of ROM_FILE (hex, upper case) – for the generated variant tr.
rom_crc32() {
    "$PYTHON" -c 'import sys, zlib; print("%08X" % zlib.crc32(open(sys.argv[1], "rb").read()))' "$ROM_FILE"
}
