/*
 * ad_lang.c – language switch of the translated ROM (variant tr): English, German, French, Spanish, Japanese.
 *
 * The ROM as built is English. The translation build (tools/translate_rom.py, "Language block")
 * leaves, for every other language, a list of records: the bytes that differ from the English
 * ROM – the name tables, the redirect table of the 16x16 strings, the briefing pointer tables,
 * the intro captions and the two intro graphics. For Japanese these are the original bytes (an
 * empty redirect table = every string is read at its original address; pointers to the rows the
 * game unpacks to $FF2000), for a translation its own copies. Switching puts the English bytes
 * back and writes the language's records over the ROM image. No code differs between the
 * languages, so the recompiled functions serve all (docs/notes/translation-rom.md).
 *
 * The game copies scenario and army names into RAM and from there into the save; those copies
 * are renamed to the current language (on a switch, and when a save made in another language
 * is loaded).
 *
 * The choice is kept in ad-port.ini in the data folder (GENESIS_USER_DIR, else the working
 * directory); AD_LANG=en|de|fr|es|jp overrides it at start. The file holds the port's other
 * choices too ("key = value" lines; ad_port_setting / ad_port_store).
 *
 * Until a language is chosen in the menu, the system's languages decide (SDL_GetPreferredLocales:
 * Windows display languages, macOS preferred languages, in their order): the first one the block
 * has, else English. Not stored, so it follows a change of the system language.
 */
#include <SDL2/SDL.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern uint8_t g_ram[0x010000];
extern uint8_t g_rom[0x400000];

#define AD_LANG_PTR       0x101FF8u
#define AD_LANG_MAX       8
#define AD_LANG_KIND_SCENARIO 1u
#define AD_LANG_KIND_ARMY     2u
#define AD_LANG_NAME_LEN      8u
#define AD_LANG_FILE      "ad-port.ini"

typedef struct {
    uint32_t addr;
    uint16_t len, kind;
    const uint8_t *data;    /* in the block (never rewritten) */
    uint8_t *en;            /* copy of the ROM image as loaded */
} LangRec;

typedef struct {
    char     code[3];
    uint32_t value;         /* the row's value string */
    LangRec *recs;
    int      count;
} Lang;

static int      s_init, s_available, s_cur;
static Lang     s_lang[AD_LANG_MAX];
static int      s_langs;
static uint32_t s_label;

static uint32_t rd32(uint32_t a)
{
    return (uint32_t)g_rom[a] << 24 | (uint32_t)g_rom[a + 1] << 16 | (uint32_t)g_rom[a + 2] << 8 | g_rom[a + 3];
}

static int in_added_area(uint32_t a) { return a >= 0x102000u && a < 0x200000u; }

static void config_path(char *out, size_t size)
{
    const char *dir = getenv("GENESIS_USER_DIR");
    if (dir && *dir) snprintf(out, size, "%s/%s", dir, AD_LANG_FILE);
    else             snprintf(out, size, "%s", AD_LANG_FILE);
}

static int language_of(const char *code)
{
    for (int i = 0; i < s_langs; i++)
        if (!strcmp(code, s_lang[i].code)) return i;
    return 0;
}

/* ---- ad-port.ini: "key = value" lines, read once, written whole on every change ---- */
#define AD_PORT_KEYS 8
static struct { char key[24], value[16]; } s_port[AD_PORT_KEYS];
static int s_port_n, s_port_read;

static void port_read(void)
{
    char path[1024], line[128], key[24], value[16];
    if (s_port_read) return;
    s_port_read = 1;
    config_path(path, sizeof path);
    FILE *f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof line, f) && s_port_n < AD_PORT_KEYS)
        if (line[0] != '#' && sscanf(line, " %23[a-z_] = %15s", key, value) == 2) {
            snprintf(s_port[s_port_n].key, sizeof s_port[0].key, "%s", key);
            snprintf(s_port[s_port_n].value, sizeof s_port[0].value, "%s", value);
            s_port_n++;
        }
    fclose(f);
}

/* The stored value of key, or NULL. */
const char *ad_port_setting(const char *key)
{
    port_read();
    for (int i = 0; i < s_port_n; i++)
        if (!strcmp(s_port[i].key, key)) return s_port[i].value;
    return NULL;
}

void ad_port_store(const char *key, const char *value)
{
    char path[1024];
    port_read();
    int i = 0;
    while (i < s_port_n && strcmp(s_port[i].key, key)) i++;
    if (i == s_port_n) {
        if (s_port_n == AD_PORT_KEYS) return;
        snprintf(s_port[i].key, sizeof s_port[0].key, "%s", key);
        s_port_n++;
    }
    snprintf(s_port[i].value, sizeof s_port[0].value, "%s", value);
    config_path(path, sizeof path);
    FILE *f = fopen(path, "w");
    if (!f) { fprintf(stderr, "[ADS] cannot write %s\n", path); return; }
    fprintf(f, "# Advanced Daisenryaku port: choices kept between launches\n");
    for (int k = 0; k < s_port_n; k++) fprintf(f, "%s = %s\n", s_port[k].key, s_port[k].value);
    fclose(f);
}

static int stored_language(void)
{
    const char *v = ad_port_setting("language");
    return v ? language_of(v) : 0;
}

/* The first of the system's preferred languages the block has (ISO 639 "ja" is the block's
 * "jp"), else 0 = English. */
static int system_language(void)
{
    SDL_Locale *list = SDL_GetPreferredLocales();
    int lang = 0;
    for (SDL_Locale *l = list; l && l->language; l++) {
        const char *code = !strcmp(l->language, "ja") ? "jp" : l->language;
        int i = 0;
        while (i < s_langs && strcmp(code, s_lang[i].code)) i++;
        if (i < s_langs) { lang = i; break; }
    }
    if (list) SDL_free(list);
    return lang;
}

static void store_language(void) { ad_port_store("language", s_lang[s_cur].code); }

/* The name at ROM address addr in language l: its record, else the English bytes (which some
 * other language's record saved), else NULL. */
static const uint8_t *name_in(int l, uint32_t addr, const uint8_t **en)
{
    const uint8_t *hit = NULL;
    *en = NULL;
    for (int k = 1; k < s_langs; k++)
        for (int i = 0; i < s_lang[k].count; i++) {
            const LangRec *r = &s_lang[k].recs[i];
            if (r->addr != addr) continue;
            *en = r->en;
            if (k == l) hit = r->data;
            break;
        }
    return hit ? hit : *en;
}

/* Names the game copied out of the tables: the save blocks $FFC800 (army records) and $FFCC00
 * (scenario name), docs/notes/saving.md. Any 8 bytes there that equal a name of another
 * language become the current language's name of the same table entry. */
static void rename_ram_names(void)
{
    static const struct { uint32_t start, size; } areas[2] = { { 0xC800u, 0x200u }, { 0xCC00u, 0x100u } };
    for (int a = 0; a < 2; a++) {
        uint8_t *p = &g_ram[areas[a].start];
        for (uint32_t o = 0; o + AD_LANG_NAME_LEN <= areas[a].size; o++) {
            int done = 0;
            for (int k = 1; k < s_langs && !done; k++) {
                for (int i = 0; i < s_lang[k].count && !done; i++) {
                    const LangRec *r = &s_lang[k].recs[i];
                    if (r->kind != AD_LANG_KIND_SCENARIO && r->kind != AD_LANG_KIND_ARMY) continue;
                    /* the field holds this entry's name in language k, or in English */
                    const uint8_t *from = !memcmp(p + o, r->data, AD_LANG_NAME_LEN) ? r->data
                                        : !memcmp(p + o, r->en, AD_LANG_NAME_LEN) ? r->en : NULL;
                    if (!from) continue;
                    const uint8_t *en, *to = name_in(s_cur, r->addr, &en);
                    if (to && memcmp(to, from, AD_LANG_NAME_LEN)) memcpy(p + o, to, AD_LANG_NAME_LEN);
                    o += AD_LANG_NAME_LEN - 1;
                    done = 1;
                }
            }
        }
    }
}

static void apply(int lang)
{
    for (int k = 1; k < s_langs; k++)               /* English everywhere */
        for (int i = 0; i < s_lang[k].count; i++)
            memcpy(&g_rom[s_lang[k].recs[i].addr], s_lang[k].recs[i].en, s_lang[k].recs[i].len);
    for (int i = 0; i < s_lang[lang].count; i++)
        memcpy(&g_rom[s_lang[lang].recs[i].addr], s_lang[lang].recs[i].data, s_lang[lang].recs[i].len);
    s_cur = lang;
    rename_ram_names();
    fprintf(stderr, "[ADS] Language: %s\n", s_lang[lang].code);
}

/* Reads one language's records from q; returns the address after their terminator, 0 on a
 * malformed list. */
static uint32_t read_records(Lang *l, uint32_t q)
{
    uint32_t start = q;
    for (int pass = 0; pass < 2; pass++) {
        int n = 0;
        q = start;
        for (;;) {
            if (q + 8 > 0x200000u) return 0;
            uint32_t addr = rd32(q);
            if (!addr) break;
            uint32_t len = (uint32_t)g_rom[q + 4] << 8 | g_rom[q + 5];
            uint32_t kind = (uint32_t)g_rom[q + 6] << 8 | g_rom[q + 7];
            if (addr + len > 0x200000u || q + 8 + len > 0x200000u) return 0;
            if ((kind == AD_LANG_KIND_SCENARIO || kind == AD_LANG_KIND_ARMY) && len != AD_LANG_NAME_LEN) return 0;
            if (pass) {
                LangRec *r = &l->recs[n];
                r->addr = addr; r->len = (uint16_t)len; r->kind = (uint16_t)kind;
                r->data = &g_rom[q + 8];
                r->en = malloc(len ? len : 1);
                if (!r->en) return 0;
                memcpy(r->en, &g_rom[addr], len);
            }
            n++;
            q += 8 + len + (len & 1u);
        }
        if (!pass) {
            l->recs = calloc((size_t)n + 1, sizeof *l->recs);
            if (!l->recs) return 0;
        }
        l->count = n;
    }
    return q + 4;
}

static void init(void)
{
    if (s_init) return;
    s_init = 1;
    if (AD_ROM_SIZE < 0x200000u) return;
    uint32_t block = rd32(AD_LANG_PTR);
    if (!in_added_area(block)) return;
    int n = g_rom[block] << 8 | g_rom[block + 1];
    if (n < 2 || n > AD_LANG_MAX) return;
    s_label = rd32(block + 4);
    if (!in_added_area(s_label)) return;
    uint32_t q = block + 8;
    for (int i = 0; i < n; i++, q += 8) {
        s_lang[i].code[0] = (char)g_rom[q]; s_lang[i].code[1] = (char)g_rom[q + 1];
        s_lang[i].value = rd32(q + 4);
        if (!in_added_area(s_lang[i].value)) return;
    }
    /* the English bytes are saved while the image is still English: all lists first */
    for (int i = 1; i < n; i++) {
        q = read_records(&s_lang[i], q);
        if (!q) return;
    }
    s_langs = n;
    s_available = 1;

    const char *e = getenv("AD_LANG");
    int lang;
    if (e && *e)                          lang = language_of(e);
    else if (ad_port_setting("language")) lang = stored_language();
    else {
        lang = system_language();
        fprintf(stderr, "[ADS] Language from the system: %s\n", s_lang[lang].code);
    }
    if (lang) apply(lang);
}

/* 1 when the ROM carries the language block (variant tr). */
int ad_lang_available(void) { init(); return s_available; }

/* The next language of the block's list. */
void ad_lang_toggle(void)
{
    init();
    if (!s_available) return;
    apply((s_cur + 1) % s_langs);
    store_language();
}

/* Strings of the "Language" row of the System settings screen (ad_spec.c). */
uint32_t ad_lang_label(void) { init(); return s_available ? s_label : 0; }
uint32_t ad_lang_value(void) { init(); return s_available ? s_lang[s_cur].value : 0; }

/* Every V-int: the first call reads the block and sets the stored language before the game
 * draws any text; later calls rename the names of a save loaded from another language. */
void ad_lang_vint(void)
{
    static uint32_t frames;
    init();
    if (s_available && (++frames & 63u) == 0) rename_ram_names();
}
