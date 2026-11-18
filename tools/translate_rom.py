#!/usr/bin/env python3
"""Build the translated ROM (variant tr) from the JP ROM and translation/script/*.toml.

    tools/translate_rom.py JP_ROM OUT_ROM [--measure]

Layout of the 3 MiB result (docs/notes/translation-rom.md):
  $000000–$0FFFFF  JP ROM; patched: $0081E0 (glyph lookup → jsr), $0081B8 (string redirect →
                   jsr), lea operands of the intro captions, name tables in place
  $100000          glyph lookup routine
  $100060          string redirect routine
  $1000C0          briefing lookup routines (one per block)
  $100100          redirect table: (original address.l, new address.l) …, 0
  $101F00          great-victory date line of the turn screen (campaign only)
  $101FF0          long pointers to what the port adds (EXTRA_POINTERS)
  $102000          new strings, then the briefing blocks and their pointer tables, the
                   language block (LANGUAGE)
  after that       extended glyphs (32 bytes each, same format as the font at $03C86A), from
                   the next $10000 boundary; the glyph lookup routine gets that address
A string selects an extended glyph with the escape FF F0 hh ll (glyph number hh ll); the original
font ends at index $35D, so FF F0 (= index $3ED) never occurs in original text.
English text is set proportionally from the Latin glyphs of the game font (or, where that is too
wide, from translation/font/small.txt) and cut into 16 px cells.
Strings of translation/script/text-*.toml ([[string]] addr/jp/en) keep their glyph count (padded
with blanks); their whole run of consecutive strings is copied to $102000+ in the original order,
and the redirect routine maps every original start address to the copy.
Name tables (8x8 font, fixed 8 characters; translation/script/names-*.toml) are overwritten in place.
Briefings (translation/script/brief-*.toml, docs/notes/briefings.md): the packed blocks stay; the
game draws from an unpacked copy in the ROM (rows with English cells, word-wrapped) through a table
of long pointers, read by a lookup routine that replaces the offset lookup at the call site.
Intro graphics (translation/script/graphics.toml): the Nemesis-packed tiles are unpacked, the
Japanese lettering is replaced by English set in the game font, the tiles are repacked after the
briefings and the lea at the call site points to them.

--measure: only print the width of every text line, write nothing.
"""
import argparse
import glob
import hashlib
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adtext  # noqa: E402
import nemesis  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "hd"))
import typeface  # noqa: E402

JP_SHA256 = "47360b90ee077c2df7bb8f8bb6f46bbea25d7e5b1fd975cdf507c1048d80b062"
ROM_SIZE = 0x300000
# The battery RAM sits at $200000-$20FFFF (header "RA"): text data stays below it, the glyph
# cells start above it. A cartridge that large shows its RAM only after a write to $A130F1,
# which the port does at reset (ad_spec.c).
TEXT_END = 0x200000
EXT_GLYPHS = 0x210000
ROUTINE = 0x100000
REDIRECT = 0x100060
TABLE = 0x100100
STRINGS = 0x102000
BRIEF_LOOKUP = 0x1000C0
ESCAPE = (0xFF, 0xF0)
MAX_TEXT_CELLS = 14   # 4-cell prefix + 14 cells from column 3 end at x = 312
TEXT_GAP = 8          # px between the fixed prefix and the text

# Glyph lookup at $0081E0: "lea $3C86A.l,a6 / adda.w d4,a6" (d4.w = index * 32) becomes
# "jsr $100000.l / nop". The routine keeps the original path and adds the escape.
PATCH_SITE = 0x0081E0
PATCH_ORIG = bytes.fromhex("4DF9 0003C86A DCC4")
PATCH_NEW = bytes.fromhex("4EB9 00100000 4E71")
ROUTINE_CODE = bytes.fromhex(
    "0C44 7DA0"        # cmpi.w #$3ED*32,d4   escape FF F0?
    "670A"             # beq.s  ext
    "4DF9 0003C86A"    # lea    $3C86A.l,a6   original font
    "DCC4"             # adda.w d4,a6
    "4E75"             # rts
    "7800"             # ext: moveq #0,d4
    "1818"             # move.b (a0)+,d4      glyph number, high byte
    "E14C"             # lsl.w  #8,d4
    "1818"             # move.b (a0)+,d4      low byte
    "EB8C"             # lsl.l  #5,d4
    "4DF9 00000000"    # lea    EXT_GLYPHS.l,a6 (set by main)
    "DDC4"             # adda.l d4,a6
    "4E75"             # rts
)

# String redirect at $0081B8 (start of the glyph decoder, called once per string by $00816A with
# a0 = string start + 1): "andi.w #$F,d1 / andi.w #$F,d2" becomes "jsr $100060.l / nop". The routine
# does both andi and looks a0 - 1 up in the table (linear, 0 ends it); on a hit a0 = copy + 1.
# The lookup compares 24 bits: the works menu table ($00BA4E) keeps the item index in the top byte
# of each string address ($010EF378 …), which the 68000 bus ignores.
# d0, d3, d4, a6 are free there (set by the decoder before use).
REDIRECT_SITE = 0x0081B8
REDIRECT_ORIG = bytes.fromhex("0241 000F 0242 000F")
REDIRECT_NEW = bytes.fromhex("4EB9 00100060 4E71")
REDIRECT_CODE = bytes.fromhex(
    "0241 000F"        # andi.w #$F,d1
    "0242 000F"        # andi.w #$F,d2
    "2008"             # move.l a0,d0
    "5380"             # subq.l #1,d0         string start
    "0280 00FFFFFF"    # andi.l #$FFFFFF,d0   24-bit address
    "4DF9 00100100"    # lea    TABLE.l,a6
    "261E"             # loop: move.l (a6)+,d3
    "670A"             # beq.s  done
    "281E"             # move.l (a6)+,d4
    "B680"             # cmp.l  d0,d3
    "66F6"             # bne.s  loop
    "2044"             # movea.l d4,a0
    "5288"             # addq.l #1,a0
    "4E75"             # done: rts
)

FIXED_CODES = {str(d): d for d in range(10)}
FIXED_CODES[" "] = 0x14
FIXED_CODES.update({chr(ord("A") + i): 0x15 + i for i in range(26)})
FIXED_CODES.update({chr(ord("a") + i): 0x2F + i for i in range(26)})

EXT_BASE_OPERAND = 0x1C   # offset of the EXT_GLYPHS operand in ROUTINE_CODE

# Briefing lookup (docs/notes/briefings.md): at the call site, "lea <offsets>,a1 / move.w
# (a1,d0.w),d0 / lea $FF2000,a0 / adda.w d0,a0" (d0.w = entry * 2) becomes "jsr <lookup> / nop × 6";
# the lookup reads a long pointer to the entry in the ROM copy.
BRIEF_SITES = {"missions": 0x002324, "results": 0x001EB4}
BRIEF_SITE_ORIG = "43F9 {table:08X} 3031 0000 41F9 00FF2000 D0C0"
BRIEF_LOOKUP_CODE = (
    "43F9 {table:08X}"  # lea    pointers.l,a1
    "D040"             # add.w  d0,d0
    "2071 0000"        # movea.l 0(a1,d0.w),a0
    "4E75"             # rts
)
BRIEF_CELLS = 17       # cells per row as in the JP (up to 17 glyphs): x = 32 to 304
BRIEF_SPACE = 5        # px per word space (menus: SPACE_WIDTH)
BRIEF_PAGE = 7         # rows per page
BRIEF_BLANK = 0x80     # control byte of a blank row; + 0x40 = last row of the entry
BRIEF_LAST = 0x40

# Great-victory date on the turn screen (docs/notes/campaign.md). The turn
# screen $008B1A draws NOW (row 15) and END (row 18); END moves to row 21 and a new line takes row
# 18: label + the date the campaign counter $FFCC2F runs out (today + counter − 1 days, the way the
# game computes END from $FFCC18). Only in a campaign ($FFCC38 = 0) and while the counter is > 0.
# The site "move.l (a7)+,$CC14.w / move.w #$8174,$C00004.l" (restores today after END) becomes
# "jsr <routine> / addq.l #4,a7 / nop × 2"; the routine finds the saved date at 4(a7).
VICTORY = 0x101F00
VICTORY_LABEL = "GREAT"
VICTORY_SITE = 0x008BB8
VICTORY_ORIG = bytes.fromhex("21DF CC14 33FC 8174 00C0 0004")
END_ROW_SITE = 0x008BA2                       # operand of "lea $FF8910,a1" (END line)
END_ROW_ORIG, END_ROW_NEW = 0xFF8910, 0xFF8A90    # row 18 → row 21 ($80 bytes per row)
# Title of the Record menu's Quit dialog ($0118B6 "lea $0EF250,a1", docs/notes/menu.md): $0EF250
# 中止 is shared with six other menus ("Cancel"); the dialog takes $0EF253 中止　, the Quit row's own
# string, instead.
QUIT_TITLE_SITE = 0x0118B8
QUIT_TITLE_ORIG, QUIT_TITLE_NEW = 0x0EF250, 0x0EF253
VICTORY_CODE = (
    "21EF 0004 CC14"   # move.l 4(a7),$CC14.w      today
    "4A38 CC38"        # tst.b  $CC38.w            1 = standard mode
    "663A"             # bne.s  done
    "7E00"             # moveq  #0,d7
    "1E38 CC2F"        # move.b $CC2F.w,d7         great-victory days left
    "6732"             # beq.s  done
    "5547"             # subq.w #2,d7
    "6B0E"             # bmi.s  draw
    "3F07"             # loop: move.w d7,-(a7)
    "4EB9 00008CDC"    # jsr    $8CDC              date + 1 day
    "3E1F"             # move.w (a7)+,d7
    "51CF FFF4"        # dbra   d7,loop
    "43F9 {row:08X}"   # draw: lea row 18,a1
    "41F9 {label:08X}" # lea    label,a0
    "4EB9 00008166"    # jsr    $8166              16x16 string
    "5889"             # addq.l #4,a1
    "4EB9 00008BD8"    # jsr    $8BD8              date (as NOW/END)
    "21EF 0004 CC14"   # move.l 4(a7),$CC14.w      today again
    "33FC 8174 00C00004"  # done: move.w #$8174,$C00004.l (replaced instruction)
    "4E75"             # rts
)

SPACE_WIDTH = 6
BASELINE = 13   # last row of capitals in the game font


def latin_glyphs(rom):
    """Proportional glyphs: char → list of columns (16-bit masks, bit y = row y)."""
    glyphs = {}
    for ch, idx in FIXED_CODES.items():
        if ch == " ":
            continue
        px = adtext.glyph_bits(rom, idx)
        cols = [sum(px[y][x] << y for y in range(16)) for x in range(16)]
        while cols and not cols[0]:
            cols.pop(0)
        while cols and not cols[-1]:
            cols.pop()
        glyphs[ch] = cols
    # Not in the font: drawn here.
    glyphs["-"] = [1 << 9] * 4
    glyphs["."] = [1 << BASELINE]
    glyphs[","] = [(1 << BASELINE) | (1 << (BASELINE + 1))]
    glyphs["'"] = [(1 << 1) | (1 << 2) | (1 << 3)]
    # Umlaut: two dots of 2x1 px in row 3 (1 px dots over the stems read as "ii" or vanish).
    u = glyphs["u"]
    w = len(u)
    glyphs["ü"] = [c | ((1 << 3) if i in (1, 2, w - 3, w - 2) else 0) for i, c in enumerate(u)]
    return glyphs


SMALL_FONT = os.path.join(adtext.ROOT, "translation", "font", "small.txt")
SMALL_TOP = 5        # row of the small font's first row inside the 16 px cell (baseline row 11)
SMALL_SPACE = 3


BIG_EXTRA = os.path.join(adtext.ROOT, "translation", "font", "big-extra.txt")
# characters the typeface adds to the fonts: German umlauts and ß, the French and Spanish
# accented letters, œ, ñ, ¿ ¡ and the ordinal signs, in both sizes
ACCENTED = "äöüßÄÖÜ" + "àâçéèêëîïôùûœÀÂÇÉÈÊÎÔ" + "áíóúñÁÍÓÚÑ¿¡"
BIG_EXTRA_CHARS = "ò'-.,°ºª" + ACCENTED
SMALL_EXTRA_CHARS = "°ºª" + ACCENTED


def brief_glyphs(rom):
    """Big font for the briefings: the Latin glyphs plus punctuation of BIG_EXTRA and ä ö é è ò."""
    glyphs = latin_glyphs(rom)
    glyphs.update(small_glyphs(BIG_EXTRA, top=0))
    for ch, base in (("ä", "a"), ("ö", "o")):
        w = len(glyphs[base])
        glyphs[ch] = [c | ((1 << 3) if i in (0, 1, w - 2, w - 1) else 0) for i, c in enumerate(glyphs[base])]
    for ch, base, rising in (("é", "e", True), ("è", "e", False), ("ò", "o", False)):
        b = glyphs[base]
        m = len(b) // 2
        hi, lo = (m + 1, m) if rising else (m, m + 1)   # accent: 2 px diagonal in rows 2-3
        glyphs[ch] = [c | ((1 << 2) if i == hi else (1 << 3) if i == lo else 0) for i, c in enumerate(b)]
    return glyphs


def small_glyphs(path=SMALL_FONT, top=SMALL_TOP):
    glyphs, cur, rows = {}, None, []

    def flush():
        if cur is not None:
            w = max(len(r) for r in rows)
            glyphs[cur] = [sum((1 << (top + y)) for y, r in enumerate(rows) if x < len(r) and r[x] == "#")
                           for x in range(w)]
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#") and not cur and not rows:
                continue
            if line.startswith("=") and len(line) == 2:
                flush()
                cur, rows = line[1], []
            elif cur is not None and line:
                rows.append(line)
    flush()
    return glyphs


def set_text(text, glyphs, space=SPACE_WIDTH):
    """Columns of the proportionally set text. Typeface fonts (typeface.TextFont, `spaced`):
    every glyph is a slot of its advance width, spaces are the font's own."""
    spaced = getattr(glyphs, "spaced", False)
    if spaced:
        space = glyphs.space
    cols = []
    for ch in text:
        if ch == " ":
            cols += [0] * space
            continue
        if ch not in glyphs:
            raise ValueError(f"character not available: {ch!r} in {text!r}")
        if cols and cols[-1] and not spaced:
            cols.append(0)
        cols += glyphs[ch]
    return cols


def cells_of(cols):
    """Cut columns into 16x16 glyphs in font format."""
    cells = []
    for start in range(0, len(cols), 16):
        c = cols[start:start + 16] + [0] * 16
        data = bytearray()
        for ox, oy in ((0, 0), (8, 0), (0, 8), (8, 8)):
            for y in range(oy, oy + 8):
                data.append(sum(((c[ox + x] >> y) & 1) << (7 - x) for x in range(8)))
        cells.append(bytes(data))
    return cells


def load_scripts(root):
    captions, tables, strings, briefs, graphics = [], [], [], [], []
    for path in sorted(glob.glob(os.path.join(root, "translation", "script", "*.toml"))):
        with open(path, "rb") as f:
            data = tomllib.load(f)
        captions += data.get("caption", [])
        if "table" in data:
            tables.append((os.path.basename(path), data["table"]["section"], data["names"]))
        strings += [dict(st, file=os.path.basename(path)) for st in data.get("string", [])]
        briefs += [dict(b, file=os.path.basename(path)) for b in data.get("briefing", [])]
        graphics += data.get("graphic", [])
    return captions, tables, strings, briefs, graphics


# Further languages (docs/notes/translation-rom.md, "Language block"): translation/<code>/*.toml,
# keyed to the entries of translation/script. Whatever a language leaves out stays English.
#   [strings]   "0EF653" = "text" | [[cell, "text"], ...] (parts) | { text = "...", font = "small" }
#   [captions]  "000EF2" = ["line", ...]          (site of the caption)
#   [graphics]  credits = "text"                  (name of the graphic)
#   [port]      "HD map" = "text"                 (strings the port adds)
#   [names.<section>]  "English name" = "name"    (8 characters of the 8x8 font)
#   [[briefing]] block, offset, text = [...]      (items as `en` in brief-*.toml)
# LANGUAGES: code, the row's value on the System settings screen; English is the ROM as built,
# Japanese the original bytes.
LANGUAGES = [("en", "English"), ("de", "Deutsch"), ("fr", "Français"), ("es", "Español"),
             ("jp", "Japanese")]


def load_language(root, code):
    data = {"strings": {}, "captions": {}, "graphics": {}, "port": {}, "names": {}, "briefing": {}}
    for path in sorted(glob.glob(os.path.join(root, "translation", code, "*.toml"))):
        with open(path, "rb") as f:
            d = tomllib.load(f)
        for key in ("strings", "captions", "graphics", "port"):
            data[key].update(d.get(key, {}))
        for section, names in d.get("names", {}).items():
            data["names"].setdefault(section, {}).update(names)
        for b in d.get("briefing", []):
            data["briefing"][(b["block"], b["offset"])] = dict(b, file=os.path.basename(path))
    data["strings"] = {int(k, 16): v for k, v in data["strings"].items()}
    data["captions"] = {int(k, 16): v for k, v in data["captions"].items()}
    return data


def language_strings(strings, texts, code):
    """The [[string]] entries with a language's texts in place of the English ones."""
    out = []
    unknown = set(texts) - {st["addr"] for st in strings}
    if unknown:
        sys.exit(f"translation/{code}: no such string: " + ", ".join(f"{a:06X}" for a in sorted(unknown)))
    for st in strings:
        st = dict(st, file=f"{code}/{st['file']}")
        t = texts.get(st["addr"])
        if isinstance(t, dict):
            st.update({k: v for k, v in t.items() if k != "text"})
            t = t.get("text")
        if isinstance(t, list):
            st["parts"] = t
        elif t is not None:
            st.pop("parts", None)
            st["en"] = t
        out.append(st)
    return out


def check_fit(jp, strings, big, small):
    """Every string that does not fit its box, as one message (render stops at the first)."""
    found = all_strings(jp)
    errors = []
    for st in strings:
        if st["addr"] not in found:
            continue
        try:
            render(dict(st), len(found[st["addr"]][0]), big, small)
        except SystemExit as e:
            errors.append(str(e))
    if errors:
        sys.exit("\n".join(errors))


def all_strings(jp):
    """Length-prefixed 16x16 strings: start → (codes, end). Block strings plus the
    length-prefixed tables of adtext.TEXT_TABLES."""
    found = {a: (codes, adtext.read_codes(jp, a)[1]) for a, (codes, _) in adtext.block_strings(jp).items()}
    for _, start, count, stride, fmt in adtext.TEXT_TABLES:
        if fmt == "len":
            for k in range(count):
                a = start + k * stride
                codes, end = adtext.read_codes(jp, a)
                found[a] = (codes, end)
    return found


def set_best(text, count_px, big, small, font=None):
    """Columns of text in the big font if it fits count_px, else in the small font."""
    for name, glyphs, space in (("big", big, SPACE_WIDTH), ("small", small, SMALL_SPACE)):
        if font and font != name:
            continue
        try:
            cols = set_text(text, glyphs, space)
        except ValueError:
            continue
        if len(cols) <= count_px:
            return cols, name
    return None, None


def render(st, count, big, small):
    """Codes (as cells and prefix codes) of a translated string with exactly count glyphs.
    Forms: en (whole width; indent = cells of blank before it), fixed + en (monospaced game-font prefix such as a year, then the
    text after TEXT_GAP px), parts = [[cell, text], ...] (text at fixed cells). Big font if it
    fits, else the small one. align: left (default), center (default when the JP starts with 2+ blanks), right."""
    prefix = [FIXED_CODES[ch] for ch in st.get("fixed", "")]
    width = (count - len(prefix)) * 16
    where = f"{st['file']}: ${st['addr']:06X}"
    font = st.get("font")
    if "parts" in st:
        cols = []
        used = None
        for cell, text in st["parts"]:
            pc, used = set_best(text, width - cell * 16, big, small, font)
            if pc is None or cell * 16 < len(cols):
                sys.exit(f"{where}: part {text!r} does not fit at cell {cell}")
            cols += [0] * (cell * 16 - len(cols)) + pc
        name = used
    else:
        gap = (TEXT_GAP if prefix and st["en"] else 0) + st.get("indent", 0) * 16
        cols, name = set_best(st["en"], width - gap, big, small, font)
        if cols is None:
            sys.exit(f"{where}: too long for {width - gap} px: {st['en']!r}")
        plain = not prefix and "indent" not in st
        # left by default (one alignment in menus); centred only where the JP
        # is indented by several blanks (timeline captions)
        align = st.get("align", "center" if st["jp"].startswith("\u3000\u3000") and plain else "left")
        free = width - gap - len(cols)
        lead = gap + (free // 2 if align == "center" else free if align == "right" else 0)
        cols = [0] * lead + cols
    cells = cells_of(cols) if any(cols) else []
    return prefix, cells, name


def apply_text(rom, jp, strings, chars, big, small, ext, pos):
    """Copy every run of consecutive strings that contains a translated one to pos, translated
    strings replaced; returns (pos, redirect table, stats). Called once per language: each gets
    its own copies and table."""
    found = all_strings(jp)
    by_addr = {}
    for st in strings:
        a = st["addr"]
        if a not in found:
            sys.exit(f"{st['file']}: ${a:06X} is no known string start")
        if adtext.decode(found[a][0], chars) != st["jp"]:
            sys.exit(f"{st['file']}: ${a:06X} script says {st['jp']!r}, ROM has {adtext.decode(found[a][0], chars)!r}")
        by_addr[a] = st
    # group = name: if one member of a group needs the small font, all members use it.
    small_groups = set()
    for st in by_addr.values():
        if "group" in st and "font" not in st and render(st, len(found[st["addr"]][0]), big, small)[2] == "small":
            small_groups.add(st["group"])
    for st in by_addr.values():
        if st.get("group") in small_groups and "font" not in st:
            st["font"] = "small"
    starts = sorted(found)
    runs, run = [], []
    for a in starts:
        if run and found[run[-1]][1] != a:
            runs.append(run)
            run = []
        run.append(a)
    runs.append(run)
    table = []
    fonts = {"big": 0, "small": 0}
    for run in runs:
        if not any(a in by_addr for a in run):
            continue
        for a in run:
            codes, end = found[a]
            table.append((a, pos))
            if a not in by_addr:
                rom[pos:pos + end - a] = jp[a:end]
                pos += end - a
                continue
            prefix, cells, font = render(by_addr[a], len(codes), big, small)
            if font:
                fonts[font] += 1
            out = bytearray(prefix)
            for cell in cells:
                n = ext.setdefault(cell, len(ext))
                out += bytes(ESCAPE) + n.to_bytes(2, "big")
            out += bytes([0x14] * (len(codes) - len(prefix) - len(cells)))
            rom[pos] = len(codes) - 1
            rom[pos + 1:pos + 1 + len(out)] = out
            pos += 1 + len(out)
    stats = f"{len(by_addr)} strings ({fonts['big']} big, {fonts['small']} small font), {len(table)} redirected"
    return pos, table, stats


def wrap(text, glyphs, width, space=SPACE_WIDTH):
    """Rows (text) of text word-wrapped to width px."""
    rows, line = [], ""
    for word in text.split():
        cand = f"{line} {word}" if line else word
        if len(set_text(cand, glyphs, space)) <= width:
            line = cand
            continue
        if not line:
            raise ValueError(f"word wider than a row: {word!r}")
        rows.append(line)
        line = word
    if line:
        rows.append(line)
    return rows


def brief_rows(en, glyphs):
    """Rows of a translated briefing (list of column lists, None = blank row). Items of en:
    "" = blank row, "^text" = one centred row, "<page>" = blank rows up to the next page (the game
    waits for a button after BRIEF_PAGE rows), "<keep>" = the rest of the entry goes on one page
    (blank rows up to the next page if it does not fit on this one); any other item is a
    paragraph, word-wrapped (one of several rows does not start on the last row of a page)."""
    width = BRIEF_CELLS * 16

    def rows_of(items):
        rows = []
        for item in items:
            if item == "":
                rows.append(None)
            elif item.startswith("^"):
                cols = set_text(item[1:].strip(), glyphs, BRIEF_SPACE)
                if len(cols) > width:
                    raise ValueError(f"centred row too long ({len(cols)} px): {item!r}")
                rows.append([0] * ((width - len(cols)) // 2) + cols)
            else:
                rows += [set_text(line, glyphs, BRIEF_SPACE) for line in wrap(item, glyphs, width, BRIEF_SPACE)]
        return rows

    rows = []
    for i, item in enumerate(en):
        if item == "<page>":
            rows += [None] * (-len(rows) % BRIEF_PAGE)
        elif item == "<keep>":
            rest = rows_of([x for x in en[i + 1:] if x not in ("<page>", "<keep>")])
            if len(rows) % BRIEF_PAGE + len(rest) > BRIEF_PAGE:
                rows += [None] * (-len(rows) % BRIEF_PAGE)
        else:
            para = rows_of([item])
            # A paragraph of several rows does not start on the last row of a page.
            if item and len(para) > 1 and len(rows) % BRIEF_PAGE == BRIEF_PAGE - 1:
                rows += [None] * (-len(rows) % BRIEF_PAGE)
            rows += para
    return rows


def apply_briefings(rom, jp, briefs, chars, glyphs, ext, pos, lang, tables=None):
    """Copy every briefing block to pos, unpacked, translated entries replaced; then a long
    pointer table per block and the lookup patch. Returns (pos, stats, tables: block → address
    of its pointer table). With `tables` (a further language) only the copies are written and
    the language's pointer table becomes a record over the English one."""
    blocks = adtext.briefings(jp, chars)
    by_key = {}
    for b in briefs:
        key = (b["block"], b["offset"])
        if b["block"] not in blocks:
            sys.exit(f"{b['file']}: unknown block {b['block']!r}")
        by_key[key] = b
    stats, made = [], {}
    for k, (name, packed, table, count) in enumerate(adtext.BRIEFINGS):
        data, _ = adtext.unpack(jp, packed)
        _, _, entries = blocks[name]
        where = {}
        done = rows_total = 0
        for offset, _, rows in entries:
            where[offset] = pos
            b = by_key.pop((name, offset), None)
            if b is None or not b.get("en"):
                _, end = adtext.briefing_rows(data, offset, chars)
                rom[pos:pos + end - offset] = data[offset:end]
                pos += end - offset
                continue
            if list(b["jp"]) != rows:
                sys.exit(f"{b['file']}: {name} +${offset:04X}: jp rows differ from the ROM")
            try:
                new_rows = brief_rows(b["en"], glyphs)
            except ValueError as e:
                sys.exit(f"{b['file']}: {name} +${offset:04X}: {e}")
            for i, cols in enumerate(new_rows):
                last = BRIEF_LAST if i == len(new_rows) - 1 else 0
                cells = cells_of(cols) if cols and any(cols) else []
                if not cells:
                    rom[pos] = BRIEF_BLANK | last
                    pos += 1
                    continue
                rom[pos] = (len(cells) - 1) | last
                pos += 1
                for cell in cells:
                    n = ext.setdefault(cell, len(ext))
                    rom[pos:pos + 4] = bytes(ESCAPE) + n.to_bytes(2, "big")
                    pos += 4
            done += 1
            rows_total += len(new_rows)
        pos = (pos + 1) & ~1
        offsets = [int.from_bytes(jp[table + 2 * i:table + 2 * i + 2], "big") for i in range(count)]
        stats.append(f"{name} {done}/{len(entries)} ({rows_total} rows)")
        if tables is not None:
            lang.append((tables[name], b"".join(where[o].to_bytes(4, "big") for o in offsets), 0))
            continue
        pointers = pos
        made[name] = pointers
        for i, o in enumerate(offsets):
            rom[pos:pos + 4] = where[o].to_bytes(4, "big")
            pos += 4
        # Japanese: the rows the game unpacked to $FF2000 (the original lookup's result)
        lang.append((pointers, b"".join((0xFF2000 + o).to_bytes(4, "big") for o in offsets), 0))
        site = BRIEF_SITES[name]
        orig = bytes.fromhex(BRIEF_SITE_ORIG.format(table=table))
        assert rom[site:site + len(orig)] == orig, f"briefing lookup at ${site:06X} not as expected"
        lookup = BRIEF_LOOKUP + 0x10 * k
        rom[site:site + len(orig)] = bytes.fromhex(f"4EB9 {lookup:08X}" + " 4E71" * 6)
        code = bytes.fromhex(BRIEF_LOOKUP_CODE.format(table=pointers))
        rom[lookup:lookup + len(code)] = code
    if by_key:
        sys.exit(f"briefings not in the ROM: {sorted(by_key)}")
    return pos, stats, made


def letter_graphic(jp, g, text, glyphs):
    """The graphic's Nemesis data with `text` in its lettering area; returns (packed, end)."""
    addr = g["addr"]
    tiles, end = nemesis.unpack(jp, addr)
    tiles = bytearray(tiles)
    w, h = g["cols"] * 8, g["rows"] * 8
    cols = set_text(text, glyphs, BRIEF_SPACE)
    if len(cols) + ("shadow" in g) > w:
        sys.exit(f"{g['name']}: {text!r} is {len(cols)} px, area {w} px")
    px = [[0] * w for _ in range(h)]
    x0 = (w - len(cols)) // 2
    for layer, dx in ((g.get("shadow"), 1), (g["ink"], 0)):
        if layer is None:
            continue
        for x, c in enumerate(cols):
            for y in range(16):
                if (c >> y) & 1 and g["top"] + y + dx < h:
                    px[g["top"] + y + dx][x0 + x + dx] = layer
    for k in range(g["cols"] * g["rows"]):
        if g["order"] == "rows":
            tx, ty = k % g["cols"], k // g["cols"]
        else:
            tx, ty = k // g["rows"], k % g["rows"]
        t = (g["first"] + k) * 32
        tiles[t:t + 32] = bytes((px[ty * 8 + y][tx * 8 + x] << 4) | px[ty * 8 + y][tx * 8 + x + 1]
                                for y in range(8) for x in range(0, 8, 2))
    return nemesis.pack(bytes(tiles)), end


def apply_graphics(rom, jp, graphics, glyphs, pos, lang, others):
    """Re-letter Nemesis-packed tiles; the repacked data goes to pos, the lea at the site to it.
    others: [(records, {name: text})] – a further language's data goes over the English one."""
    stats = []
    for g in graphics:
        site, addr = g["site"], g["addr"]
        if rom[site - 2:site] != b"\x41\xF9" or int.from_bytes(rom[site:site + 4], "big") != addr:
            sys.exit(f"${site:06X}: no 'lea ${addr:06X},a0'")
        packed, end = letter_graphic(jp, g, g["en"], glyphs)
        pos += pos & 1
        rom[pos:pos + len(packed)] = packed
        rom[site:site + 4] = pos.to_bytes(4, "big")
        stats.append(f"{g['name']} {len(packed)} B (was {end - addr})")
        lang.append((pos, bytes(jp[addr:end]), 0))      # Japanese: the original packed tiles
        room = max(len(packed), end - addr)
        for records, texts in others:
            if texts.get(g["name"], g["en"]) != g["en"]:
                data = letter_graphic(jp, g, texts[g["name"]], glyphs)[0]
                records.append((pos, data, 0))
                room = max(room, len(data))
        pos += room
    return pos, stats


ASCII_EXTRA = {" ": "\u3000", "-": "―", "'": "’"}


def encode_name(text, inv):
    """8x8 codes of an English name: ASCII as the full-width characters of the charmap,
    plus Ⅰ–Ⅹ, ㎜, ㎏ as they are."""
    codes = []
    for ch in text:
        if ch in ASCII_EXTRA:
            ch = ASCII_EXTRA[ch]
        elif "!" <= ch <= "~":
            ch = chr(ord(ch) + 0xFEE0)
        code = inv.get(ch)
        if code is None or code >= 0xA8:
            sys.exit(f"not in the 8x8 font: {ch!r} in {text!r}")
        codes.append(code)
    return codes


def apply_names(rom, jp, tables, chars, lang, others):
    """Overwrite names of the fixed tables (adtext.TEXT_TABLES) in place; returns counts.
    others: [(code, records, {section: {English name: name}})] – further languages, as records
    over the English name."""
    inv = {c: i for i, c in chars.items()}
    specs = {t[0]: t for t in adtext.TEXT_TABLES}
    stats = []
    for fname, section, names in tables:
        _, start, count, stride, fmt = specs[section]
        width = 8
        offset = 1 if fmt == "len" else 0   # "len": length byte 7 (= 8 characters) stays
        used, used_other = set(), {}
        done = 0
        for k in range(count):
            a = start + k * stride + offset
            name = adtext.decode(list(jp[a:a + width]), chars).rstrip("\u3000")
            if name not in names:
                continue
            en = names[name]
            if len(en) > width:
                sys.exit(f"{fname}: longer than {width}: {en!r}")
            codes = encode_name(en, inv)
            rom[a:a + width] = bytes(codes + [0x14] * (width - len(codes)))
            if rom[a:a + width] != jp[a:a + width]:
                lang.append((a, bytes(jp[a:a + width]), LANG_KINDS.get(section, 0)))
            used.add(name)
            done += 1
            for code, records, more in others:
                other = more.get(section, {}).get(en)
                if other is None or other == en:
                    continue
                if len(other) > width:
                    sys.exit(f"translation/{code}: {section}: longer than {width}: {other!r}")
                used_other.setdefault(code, set()).add(en)
                data = bytes(encode_name(other, inv) + [0x14] * (width - len(other)))
                records.append((a, data, LANG_KINDS.get(section, 0)))
        unknown = set(names) - used
        if unknown:
            sys.exit(f"{fname}: not in table {section}: {sorted(unknown)}")
        for code, records, more in others:
            unknown = set(more.get(section, {})) - used_other.get(code, set()) - set(names.values())
            if unknown:
                sys.exit(f"translation/{code}: not an English name of {section}: {sorted(unknown)}")
        stats.append(f"{section} {done}/{count}")
    return stats


# Strings the port adds (no JP original). The port finds them through long pointers at
# EXTRA_POINTERS (recomp/game/ad_spec.c): [0] label of the "HD map" row of the System settings
# screen (docs/notes/menu.md), same cell count and font as the other rows of that screen.
EXTRA_POINTERS = 0x101FF0
EXTRA_STRINGS = [("HD map", 0x0EF4BD, "settings")]     # text, a row of the same list, its group
# [1] the title menu's start-year row (docs/notes/campaign.md): eight strings of the 8x8 menu
# font ($008104: count - 1, then glyph codes), all of one length, "CAMPAIGN START 1939" … "1946".
START_YEARS = range(1939, 1947)
START_LABEL = "CAMPAIGN START"
# right after them: the title menu's last row, which ends the game (docs/notes/menu.md)
QUIT_LABEL = "QUIT GAME"


def apply_extra(rom, jp, strings, big, small, ext, pos):
    found = all_strings(jp)
    for i, (text, like, group) in enumerate(EXTRA_STRINGS):
        count = len(found[like][0])
        st = {"file": "translate_rom.py", "addr": 0, "jp": "", "en": text}
        font = next((s.get("font") for s in strings if s.get("group") == group and s.get("font")), None)
        if font:
            st["font"] = font
        prefix, cells, _ = render(st, count, big, small)
        out = bytearray(prefix)
        for cell in cells:
            n = ext.setdefault(cell, len(ext))
            out += bytes(ESCAPE) + n.to_bytes(2, "big")
        out += bytes([0x14] * (count - len(prefix) - len(cells)))
        ptr = EXTRA_POINTERS + 4 * i
        assert rom[ptr:ptr + 4] == b"\xFF" * 4, f"${ptr:06X} not free"
        rom[ptr:ptr + 4] = pos.to_bytes(4, "big")
        rom[pos] = count - 1
        rom[pos + 1:pos + 1 + len(out)] = out
        pos += 1 + 4 * count                 # room for any text of count cells (other languages)
    ptr = EXTRA_POINTERS + 4 * len(EXTRA_STRINGS)
    assert rom[ptr:ptr + 4] == b"\xFF" * 4, f"${ptr:06X} not free"
    rom[ptr:ptr + 4] = pos.to_bytes(4, "big")
    for year in START_YEARS:
        text = f"{START_LABEL} {year}"
        rom[pos] = len(text) - 1
        rom[pos + 1:pos + 1 + len(text)] = bytes(FIXED_CODES[c] for c in text)
        pos += 1 + len(text)
    rom[pos] = len(QUIT_LABEL) - 1
    rom[pos + 1:pos + 1 + len(QUIT_LABEL)] = bytes(FIXED_CODES[c] for c in QUIT_LABEL)
    pos += 1 + len(QUIT_LABEL)
    return pos


# Language switch (docs/notes/translation-rom.md, "Language block"; recomp/game/ad_lang.c). The
# ROM as built is English. For every other language of LANGUAGES the block lists the bytes that
# differ; the port shows a language by writing its records over the ROM image (after putting the
# English bytes back). Block, found through the long pointer at LANGUAGE_POINTER:
#   count.w (languages), 0.w, label.l (string of the "Language" row)
#   per language: code (2 ASCII characters), 0.w, value.l (the row's value string)
#   per language after the first: records address.l, length.w, kind.w, bytes (padded to even)
#   ...; address 0 ends a language's records
# kind 1 / 2 = a scenario / army name (8 characters): the game copies these into RAM and into
# the save, so the port renames the copies as well.
LANGUAGE_POINTER = 0x101FF8
LANG_KINDS = {"scenarios": 1, "armies": 2}
LANGUAGE_LABEL = "Language"
# "Restart" (recomp/game/ad_restart.c, docs/notes/campaign.md): in the campaign the Record menu's
# row "Give up" restarts the map. Two strings, back to back, found through RESTART_POINTER: the
# row's label and the title of its Cancel / Exec. dialog, with the cell counts of the "Give up"
# strings they stand in for.
RESTART_POINTER = 0x101FFC
RESTART_STRINGS = [("Restart", 0x0EF463), ("Restart", 0x0EF45F)]
LANGUAGE_VALUE_CELLS = 4          # as the screen's other values (REAL)
# Automatic fast-forward rows of the System settings screen (recomp/game/ad_spec.c,
# docs/notes/menu.md): found through SPEED_POINTER, six long pointers – the labels "Fast enemy
# turn" (ON/OFF) and "Enemy battles", then the four values of the second row (the same in every
# language) – followed by the strings.
SPEED_POINTER = 0x101FEC
SPEED_LABELS = ["Fast enemy turn", "Enemy battles"]
SPEED_VALUES = ["1x", "2x", "4x", "MAX"]


def string_bytes(st, count, big, small, ext):
    """A string of count glyphs set like the translated ones: length byte and codes."""
    prefix, cells, _ = render(st, count, big, small)
    out = bytearray([count - 1]) + bytearray(prefix)
    for cell in cells:
        n = ext.setdefault(cell, len(ext))
        out += bytes(ESCAPE) + n.to_bytes(2, "big")
    return bytes(out + bytes([0x14] * (count - len(prefix) - len(cells))))


def port_string(text, group, strings):
    """A string the port adds, in the font of the list it joins."""
    st = {"file": "translate_rom.py", "addr": 0, "jp": "", "en": text}
    font = next((s.get("font") for s in strings if s.get("group") == group and s.get("font")), None)
    if font:
        st["font"] = font
    return st


def apply_language(rom, jp, strings, big, small, ext, pos, records, port):
    """The strings of the Language row and the language block; returns (pos, stats).
    records: {code: [(address, bytes, kind)]}, port: {code: (strings, {English text: text})}."""
    found = all_strings(jp)
    count = len(found[0x0EF4BD][0])
    label = pos
    data = string_bytes(port_string(LANGUAGE_LABEL, "settings", strings), count, big, small, ext)
    rom[pos:pos + len(data)] = data
    pos += 1 + 4 * count
    # the "HD map" label of apply_extra and the label above, in the other languages
    hd_map = int.from_bytes(rom[EXTRA_POINTERS:EXTRA_POINTERS + 4], "big")
    added = [(hd_map, EXTRA_STRINGS[0][0], count, "settings"), (label, LANGUAGE_LABEL, count, "settings")]
    assert rom[RESTART_POINTER:RESTART_POINTER + 4] == b"\xFF" * 4, f"${RESTART_POINTER:06X} not free"
    rom[RESTART_POINTER:RESTART_POINTER + 4] = pos.to_bytes(4, "big")
    for text, like in RESTART_STRINGS:
        n = len(found[like][0])
        data = string_bytes(port_string(text, None, strings), n, big, small, ext)
        rom[pos:pos + len(data)] = data
        added.append((pos, text, n, None))
        pos += 1 + 4 * n
    assert rom[SPEED_POINTER:SPEED_POINTER + 4] == b"\xFF" * 4, f"${SPEED_POINTER:06X} not free"
    pos += pos & 1
    rom[SPEED_POINTER:SPEED_POINTER + 4] = pos.to_bytes(4, "big")
    table, pos = pos, pos + 4 * (len(SPEED_LABELS) + len(SPEED_VALUES))
    for i, text in enumerate(SPEED_LABELS):
        rom[table + 4 * i:table + 4 * i + 4] = pos.to_bytes(4, "big")
        data = string_bytes(port_string(text, "settings", strings), count, big, small, ext)
        rom[pos:pos + len(data)] = data
        added.append((pos, text, count, "settings"))
        pos += 1 + 4 * count
    speeds = [{"file": "translate_rom.py", "addr": 0, "jp": "", "en": v} for v in SPEED_VALUES]
    for i, v in enumerate(speeds, len(SPEED_LABELS)):
        rom[table + 4 * i:table + 4 * i + 4] = pos.to_bytes(4, "big")
        data = string_bytes(v, LANGUAGE_VALUE_CELLS, big, small, ext)
        rom[pos:pos + len(data)] = data
        pos += len(data)
    for code, (other_strings, texts) in port.items():
        for addr, text, n, group in added:
            if texts.get(text, text) != text:
                st = port_string(texts[text], group, other_strings)
                records[code].append((addr, string_bytes(st, n, big, small, ext), 0))
    # the values: one font for all, the small one if any is too wide for the big one
    values = [{"file": "translate_rom.py", "addr": 0, "jp": "", "en": v} for _, v in LANGUAGES]
    if any(render(v, LANGUAGE_VALUE_CELLS, big, small)[2] == "small" for v in values):
        for v in values:
            v["font"] = "small"
    value_at = []
    for v in values:
        value_at.append(pos)
        data = string_bytes(v, LANGUAGE_VALUE_CELLS, big, small, ext)
        rom[pos:pos + len(data)] = data
        pos += len(data)

    pos += pos & 1
    assert rom[LANGUAGE_POINTER:LANGUAGE_POINTER + 4] == b"\xFF" * 4, f"${LANGUAGE_POINTER:06X} not free"
    rom[LANGUAGE_POINTER:LANGUAGE_POINTER + 4] = pos.to_bytes(4, "big")
    block = bytearray(len(LANGUAGES).to_bytes(2, "big") + bytes(2) + label.to_bytes(4, "big"))
    for (code, _), at in zip(LANGUAGES, value_at):
        block += code.encode("ascii") + bytes(2) + at.to_bytes(4, "big")
    stats = []
    for code, _ in LANGUAGES[1:]:
        for addr, data, kind in sorted(records[code]):
            block += addr.to_bytes(4, "big") + len(data).to_bytes(2, "big") + kind.to_bytes(2, "big") + data
            block += bytes(len(data) & 1)
        block += bytes(4)
        stats.append(f"{code} {len(records[code])} records, {sum(len(d) for _, d, _ in records[code])} bytes")
    rom[pos:pos + len(block)] = block
    return pos + len(block), ", ".join(stats)


def apply_victory_date(rom):
    """Turn screen: great-victory date between NOW and END (VICTORY_CODE)."""
    assert rom[VICTORY_SITE:VICTORY_SITE + len(VICTORY_ORIG)] == VICTORY_ORIG, \
        f"turn screen at ${VICTORY_SITE:06X} not as expected"
    assert int.from_bytes(rom[END_ROW_SITE:END_ROW_SITE + 4], "big") == END_ROW_ORIG
    rom[END_ROW_SITE:END_ROW_SITE + 4] = END_ROW_NEW.to_bytes(4, "big")
    rom[VICTORY_SITE:VICTORY_SITE + len(VICTORY_ORIG)] = bytes.fromhex(f"4EB9 {VICTORY:08X} 588F 4E71 4E71")
    col = 14 - 2 * len(VICTORY_LABEL)         # label ends where NOW/END end (column 14)
    code = bytes.fromhex(VICTORY_CODE.format(row=END_ROW_ORIG - 0x10 + 2 * col, label=0))
    label = VICTORY + len(code)
    code = bytes.fromhex(VICTORY_CODE.format(row=END_ROW_ORIG - 0x10 + 2 * col, label=label))
    text = bytes([len(VICTORY_LABEL) - 1] + [FIXED_CODES[c] for c in VICTORY_LABEL])
    assert label + len(text) <= STRINGS
    rom[VICTORY:label] = code
    rom[label:label + len(text)] = text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jp_rom")
    ap.add_argument("out_rom", nargs="?")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--game-font", action="store_true",
                    help="set the text with the game's pixel fonts (before 07.11.2026) instead of the typeface")
    args = ap.parse_args()

    jp = open(args.jp_rom, "rb").read()
    if hashlib.sha256(jp).hexdigest() != JP_SHA256:
        sys.exit(f"not the JP ROM (Rev A): {args.jp_rom}")
    chars = adtext.load_charmap()
    game_glyphs = latin_glyphs(jp)
    captions, tables, strings, briefs, graphics = load_scripts(adtext.ROOT)
    if args.game_font:
        glyphs, small, brief = game_glyphs, small_glyphs(), brief_glyphs(jp)
    else:
        # the typeface sets all text (one baseline, its own spacing; docs/notes/hd-graphics.md)
        brief = typeface.text_font("big", brief_glyphs(jp), extra=BIG_EXTRA_CHARS)
        glyphs = brief
        small = typeface.text_font("small", small_glyphs(), extra=SMALL_EXTRA_CHARS)

    rom = bytearray(jp) + b"\xFF" * (ROM_SIZE - len(jp))
    assert rom[PATCH_SITE:PATCH_SITE + 8] == PATCH_ORIG, "glyph lookup at $0081E0 not as expected"
    rom[PATCH_SITE:PATCH_SITE + 8] = PATCH_NEW
    rom[ROUTINE:ROUTINE + len(ROUTINE_CODE)] = ROUTINE_CODE
    assert rom[REDIRECT_SITE:REDIRECT_SITE + 8] == REDIRECT_ORIG, "glyph decoder at $0081B8 not as expected"
    rom[REDIRECT_SITE:REDIRECT_SITE + 8] = REDIRECT_NEW
    rom[REDIRECT:REDIRECT + len(REDIRECT_CODE)] = REDIRECT_CODE
    assert int.from_bytes(rom[QUIT_TITLE_SITE:QUIT_TITLE_SITE + 4], "big") == QUIT_TITLE_ORIG
    rom[QUIT_TITLE_SITE:QUIT_TITLE_SITE + 4] = QUIT_TITLE_NEW.to_bytes(4, "big")
    assert ROUTINE + len(ROUTINE_CODE) <= REDIRECT and REDIRECT + len(REDIRECT_CODE) <= BRIEF_LOOKUP

    ext = {}          # glyph data → glyph number (identical cells are shared)
    records = {code: [] for code, _ in LANGUAGES[1:]}     # code → [(address, bytes, kind)]
    lang = records["jp"]
    more = {code: load_language(adtext.ROOT, code) for code in records if code != "jp"}
    # the other languages' strings, before apply_text fixes the fonts of the English groups
    more_strings = {code: language_strings(strings, data["strings"], code) for code, data in more.items()}
    pos = STRINGS
    worst = 0
    def caption_data(cap, texts):
        """A caption's lines as string bytes; checks the JP lines. Returns (bytes, JP end)."""
        nonlocal worst
        src = cap["addr"]
        data = bytearray()
        for line, text in zip(cap["lines"], texts):
            codes, src = adtext.read_codes(jp, src)
            if adtext.decode(codes, chars) != line["jp"]:
                sys.exit(f"${cap['addr']:06X}: script says {line['jp']!r}, ROM has {adtext.decode(codes, chars)!r}")
            cols = [0] * TEXT_GAP + set_text(text, glyphs)
            cells = cells_of(cols)
            worst = max(worst, len(cols))
            if args.measure:
                print(f"{len(cols):4d} px {len(cells):3d} cells  {text}")
            if len(cells) > MAX_TEXT_CELLS:
                sys.exit(f"too long ({len(cols)} px > {MAX_TEXT_CELLS * 16}): {text!r}")
            out = bytearray(FIXED_CODES[ch] for ch in line["fixed"])
            for cell in cells:
                n = ext.setdefault(cell, len(ext))
                out += bytes(ESCAPE) + n.to_bytes(2, "big")
            data += bytes([len(line["fixed"]) + len(cells) - 1]) + out
        return bytes(data), src

    for cap in captions:
        site, addr = cap["site"], cap["addr"]
        if rom[site:site + 2] != b"\x41\xF9" or int.from_bytes(rom[site + 2:site + 6], "big") != addr:
            sys.exit(f"${site:06X}: no 'lea ${addr:06X},a0'")
        data, src = caption_data(cap, [line["text"] for line in cap["lines"]])
        rom[pos:pos + len(data)] = data
        rom[site + 2:site + 6] = pos.to_bytes(4, "big")
        # Japanese: the original lines in the caption's place; room for the longest version
        lang.append((pos, bytes(jp[addr:src]), 0))
        room = max(len(data), src - addr)
        for code, texts in more.items():
            if site in texts["captions"]:
                if len(texts["captions"][site]) != len(cap["lines"]):
                    sys.exit(f"translation/{code}: caption {site:06X} needs {len(cap['lines'])} lines")
                other = caption_data(cap, texts["captions"][site])[0]
                records[code].append((pos, other, 0))
                room = max(room, len(other))
        pos += room
    if args.measure:
        print(f"widest line {worst} px of {MAX_TEXT_CELLS * 16}, {len(ext)} extended glyphs")
        return
    for code in more:
        check_fit(jp, more_strings[code], glyphs, small)
    pos, table, text_stats = apply_text(rom, jp, strings, chars, glyphs, small, ext, pos)
    pos = apply_extra(rom, jp, strings, glyphs, small, ext, pos)
    pos, brief_stats, brief_tables = apply_briefings(rom, jp, briefs, chars, brief, ext, pos, lang)
    lang.append((TABLE, bytes(4), 0))       # Japanese: an empty redirect table
    more_stats = []
    for code, data in more.items():
        # the language's own copies of the strings; its redirect table goes over the English one
        pos, other, stats = apply_text(rom, jp, more_strings[code], chars, glyphs, small, ext, pos)
        assert [a for a, _ in other] == [a for a, _ in table]
        records[code].append((TABLE, b"".join(a.to_bytes(4, "big") + b.to_bytes(4, "big") for a, b in other), 0))
        unknown = set(data["briefing"]) - {(b["block"], b["offset"]) for b in briefs}
        if unknown:
            sys.exit(f"translation/{code}: no such briefing: {sorted(unknown)}")
        other_briefs = [dict(b, en=data["briefing"].get((b["block"], b["offset"]), {}).get("text", b.get("en")))
                        for b in briefs]
        pos, bstats, _ = apply_briefings(rom, jp, other_briefs, chars, brief, ext, pos, records[code],
                                         tables=brief_tables)
        more_stats.append(f"{code}: text {stats}; briefings {', '.join(bstats)}")
    pos, gfx_stats = apply_graphics(rom, jp, graphics, game_glyphs, pos, lang,
                                    [(records[c], d["graphics"]) for c, d in more.items()])   # tile pictures, no HD text
    name_stats = apply_names(rom, jp, tables, chars, lang, [(c, records[c], d["names"]) for c, d in more.items()])
    pos, lang_stats = apply_language(rom, jp, strings, glyphs, small, ext, pos, records,
                                     {c: (more_strings[c], d["port"]) for c, d in more.items()})
    assert pos <= TEXT_END, f"text area full: up to ${pos:06X}"
    ext_glyphs = EXT_GLYPHS
    rom[ROUTINE + EXT_BASE_OPERAND:ROUTINE + EXT_BASE_OPERAND + 4] = ext_glyphs.to_bytes(4, "big")
    assert TABLE + 8 * len(table) + 4 <= VICTORY, "redirect table full"
    apply_victory_date(rom)
    for i, (a, b) in enumerate(table):
        rom[TABLE + 8 * i:TABLE + 8 * i + 8] = a.to_bytes(4, "big") + b.to_bytes(4, "big")
    rom[TABLE + 8 * len(table):TABLE + 8 * len(table) + 4] = bytes(4)
    assert ext_glyphs + len(ext) * 32 <= ROM_SIZE, f"glyph area full: {len(ext)} glyphs from ${ext_glyphs:06X}"
    for cell, n in ext.items():
        rom[ext_glyphs + n * 32:ext_glyphs + n * 32 + 32] = cell

    # Header: ROM end and checksum (word sum from $000200).
    rom[0x1A4:0x1A8] = (ROM_SIZE - 1).to_bytes(4, "big")
    checksum = sum(int.from_bytes(rom[i:i + 2], "big") for i in range(0x200, ROM_SIZE, 2)) & 0xFFFF
    rom[0x18E:0x190] = checksum.to_bytes(2, "big")

    os.makedirs(os.path.dirname(os.path.abspath(args.out_rom)), exist_ok=True)
    with open(args.out_rom, "wb") as f:
        f.write(rom)
    print(f"{args.out_rom}: {len(captions)} captions, text up to ${pos:06X}, "
          f"{len(ext)} extended glyphs from ${ext_glyphs:06X} up to ${ext_glyphs + 32 * len(ext):06X}")
    print("text: " + text_stats)
    print("briefings: " + ", ".join(brief_stats))
    print("names: " + ", ".join(name_stats))
    print("graphics: " + ", ".join(gfx_stats))
    print("language: " + lang_stats)
    for line in more_stats:
        print(line)


if __name__ == "__main__":
    main()
