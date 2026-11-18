/*
 * ad_frame.c – camouflage frame in the 16:9 side margins of the HD frame (docs/notes/frame.md).
 *
 * Outside the zoomed map the picture is 320 px wide and the margins (framework patch 0010)
 * would be black. This draws a frame there: the cream double line of the game's panels and a
 * plate painted in the camouflage of the country in play; in a battle the left and right
 * margin show the two countries fighting. All of it is drawn by this file (no ROM data, no
 * art files) and written as ARGB through the hook of framework patch 0011.
 *
 * Presentation only – nothing the game reads changes. AD_FRAME=0 turns it off.
 */
#include "genesis_machine.h"
#include "genesis_vdp.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern uint8_t g_rom[0x400000];
extern uint8_t g_ram[0x010000];

int ad_mapzoom_active(void);            /* ad_mapzoom.c: zoomed map on screen (lines 8–167) */

/* ---- RAM / ROM (docs/notes/frame.md) ---- */
#define RAM_VINT_MODE 0x0110u           /* 6 = intro, 4 = battle animation */
#define RAM_SCREEN    0xCD04u           /* $46/$66 = battle */
#define RAM_ARMY      0xCC17u           /* army in play, 0–7 */
#define RAM_ARMY_PTR  0xCC10u           /* pointer to its record; 0 = no scenario loaded yet */
#define RAM_ARMIES    0xC800u           /* 8 records of $20 bytes, name at +$10 */
#define RAM_UNITS     0xB000u           /* 256 records of $18 bytes, army at +$0F */
#define RAM_BATTLE_A  0xD060u           /* attacker: unit record at +$08 */
#define RAM_BATTLE_D  0xD080u           /* defender, same layout */
#define RAM_OBJECTS_A 0xD100u           /* objects of the attacker's side, $40 bytes each */
#define RAM_OBJECTS_D 0xD380u           /* objects of the defender's side */
#define ROM_ARMY_NAMES 0x0233F0u        /* 82 entries of 9 bytes: length, 8 characters */
#define ARMY_NAMES 82

/* ---- countries ---- */
enum { N_MINOR, N_GERMANY, N_POLAND, N_BRITAIN, N_FRANCE, N_USSR, N_USA, N_ITALY, N_FINLAND, N_COUNT };

/* Country of each entry of the army name table (nations, army groups, fronts, commanders). */
static const uint8_t s_army_nation[ARMY_NAMES] = {
    [1] = N_GERMANY, [3] = N_GERMANY, [5] = N_GERMANY, [11] = N_GERMANY, [13] = N_GERMANY,
    [14] = N_GERMANY, [26] = N_GERMANY, [29] = N_GERMANY, [33] = N_GERMANY, [38] = N_GERMANY,
    [40] = N_GERMANY, [50] = N_GERMANY, [51] = N_GERMANY, [52] = N_GERMANY, [54] = N_GERMANY,
    [55] = N_GERMANY, [61] = N_GERMANY, [62] = N_GERMANY, [66] = N_GERMANY, [71] = N_GERMANY,
    [76] = N_GERMANY,
    [2] = N_POLAND,
    [6] = N_BRITAIN, [43] = N_BRITAIN, [44] = N_BRITAIN, [56] = N_BRITAIN, [57] = N_BRITAIN,
    [69] = N_BRITAIN, [70] = N_BRITAIN, [79] = N_BRITAIN, [80] = N_BRITAIN,
    [7] = N_FRANCE, [45] = N_FRANCE, [46] = N_FRANCE,
    [18] = N_USSR, [20] = N_USSR, [21] = N_USSR, [22] = N_USSR, [24] = N_USSR, [27] = N_USSR,
    [28] = N_USSR, [30] = N_USSR, [31] = N_USSR, [32] = N_USSR, [34] = N_USSR, [35] = N_USSR,
    [36] = N_USSR, [37] = N_USSR, [39] = N_USSR, [41] = N_USSR, [42] = N_USSR, [60] = N_USSR,
    [74] = N_USSR, [75] = N_USSR, [77] = N_USSR, [78] = N_USSR,
    [49] = N_USA, [63] = N_USA, [64] = N_USA, [65] = N_USA, [67] = N_USA, [68] = N_USA,
    [72] = N_USA, [73] = N_USA,
    [12] = N_ITALY, [59] = N_ITALY,
    [19] = N_FINLAND,
};

/* ---- reference size: the art is made for scale 4 and sampled for other scales ---- */
#define RS 4
#define RW (GVDP_HD_MAX_MARGIN * RS)    /* columns, by distance from the picture's edge */
#define RH (224 * RS)

typedef struct { uint8_t r, g, b; } Rgb;
static const Rgb CREAM = { 255, 255, 206 }, MID = { 119, 119, 87 }, BLACK = { 0, 0, 0 };

/* ---- value noise ---- */
typedef struct { float g[64][64]; float cell; } Noise;
static uint32_t s_rng;
static float rnd(void) { s_rng = s_rng * 1664525u + 1013904223u; return (float)(s_rng >> 8) / 16777216.0f; }
static void noise_init(Noise *n, uint32_t seed, float cell)
{
    s_rng = seed * 2654435761u + 12345u;
    for (int y = 0; y < 64; y++) for (int x = 0; x < 64; x++) n->g[y][x] = rnd();
    n->cell = cell;
}
static float noise_at(const Noise *n, float x, float y)
{
    x /= n->cell; y /= n->cell;
    int xi = (int)x, yi = (int)y;
    float fx = x - (float)xi, fy = y - (float)yi;
    fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy);
    float a = n->g[yi & 63][xi & 63], b = n->g[yi & 63][(xi + 1) & 63];
    float c = n->g[(yi + 1) & 63][xi & 63], d = n->g[(yi + 1) & 63][(xi + 1) & 63];
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy;
}
static Noise s_n[4];
static float fbm(int k, float x, float y) { return 0.7f * noise_at(&s_n[k], x, y) + 0.3f * noise_at(&s_n[k + 1], x, y); }

/* ---- patterns: colour index of a pixel ---- */
typedef struct {
    int kind;                   /* 0 plain, 1 bands, 2 patches on a base, 3 splinter */
    uint32_t seed;
    float cell, cell2, sx, sy, cut1, cut2;
    int outline;
    Rgb col[3];
} Pattern;

static const Pattern s_pattern[N_COUNT] = {
    [N_MINOR]   = { 0, 1, 0, 0, 1, 1, 0, 0, 0, { { 66, 69, 48 } } },
    /* splinter: grey-green with brown and green shards */
    [N_GERMANY] = { 3, 11, 0, 0, 1, 1, 0, 0, 0, { { 124, 128, 98 }, { 112, 74, 48 }, { 62, 88, 54 } } },
    /* 1936 scheme: sand, olive and dark brown in soft horizontal bands */
    [N_POLAND]  = { 1, 21, 95, 0, 0.45f, 1, 0.42f, 0.60f, 0, { { 84, 94, 56 }, { 188, 168, 110 }, { 78, 54, 38 } } },
    /* dark green and dark earth in broad bands */
    [N_BRITAIN] = { 1, 33, 85, 0, 0.9f, 0.5f, 0.50f, 2, 0, { { 70, 86, 52 }, { 122, 98, 62 }, { 0, 0, 0 } } },
    /* 1940 scheme: green, ochre and brown patches with dark outlines */
    [N_FRANCE]  = { 1, 41, 105, 0, 1, 1, 0.40f, 0.58f, 1, { { 82, 106, 62 }, { 186, 152, 84 }, { 112, 72, 46 } } },
    /* green with a few dark brown and dark green patches */
    [N_USSR]    = { 2, 51, 120, 90, 1, 1, 0.66f, 0.70f, 0, { { 76, 96, 56 }, { 64, 54, 38 }, { 40, 52, 34 } } },
    /* olive drab with black patches */
    [N_USA]     = { 2, 61, 110, 70, 1, 1, 0.62f, 0.74f, 0, { { 88, 88, 52 }, { 32, 32, 26 }, { 32, 32, 26 } } },
    /* sand with small green and red-brown spots */
    [N_ITALY]   = { 2, 71, 34, 30, 1, 1, 0.60f, 0.66f, 0, { { 198, 174, 122 }, { 82, 102, 58 }, { 128, 72, 46 } } },
    /* moss green, grey and brown */
    [N_FINLAND] = { 1, 81, 130, 0, 1, 1, 0.42f, 0.60f, 0, { { 72, 96, 62 }, { 152, 152, 136 }, { 102, 78, 52 } } },
};

#define SPLINTERS 280
static struct { float x, y; int c; } s_pts[SPLINTERS];

static void pattern_begin(const Pattern *p)
{
    noise_init(&s_n[0], p->seed, p->cell ? p->cell : 1);
    noise_init(&s_n[1], p->seed + 1, (p->cell ? p->cell : 1) / 2.7f);
    noise_init(&s_n[2], p->seed + 2, p->cell2 ? p->cell2 : 1);
    noise_init(&s_n[3], p->seed + 3, (p->cell2 ? p->cell2 : 1) / 2.7f);
    if (p->kind == 3) {
        s_rng = p->seed * 7919u;
        for (int i = 0; i < SPLINTERS; i++) {
            s_pts[i].x = rnd() * (RW + 80) - 40;
            s_pts[i].y = rnd() * (RH + 80) - 40;
            float w = rnd() * 11;                       /* weights 5 : 3 : 3 */
            s_pts[i].c = w < 5 ? 0 : w < 8 ? 1 : 2;
        }
    }
}
static int band_index(const Pattern *p, float x, float y)
{
    float v = fbm(0, x * p->sx, y * p->sy);
    return v < p->cut1 ? 0 : v < p->cut2 ? 1 : 2;
}
/* Colour index 0–2, 3 = outline, 4–6 = index 0–2 darkened (rain strokes of the splinter). */
static int pattern_at(const Pattern *p, int x, int y)
{
    float fx = (float)x, fy = (float)y;
    switch (p->kind) {
    case 1: {
        int i = band_index(p, fx, fy);
        if (p->outline && (band_index(p, fx + 5, fy) != i || band_index(p, fx - 5, fy) != i ||
                           band_index(p, fx, fy + 5) != i || band_index(p, fx, fy - 5) != i)) return 3;
        return i;
    }
    case 2:
        if (fbm(0, fx, fy) > p->cut1) return 1;
        if (fbm(2, fx, fy) > p->cut2) return 2;
        return 0;
    case 3: {
        /* nearest point in a sheared metric: long angular shards */
        float best = 1e9f; int c = 0;
        for (int i = 0; i < SPLINTERS; i++) {
            float dx = fx - s_pts[i].x, dy = fy - s_pts[i].y;
            float a = dx + dy * 0.45f, b = dx * 0.6f - dy * 0.9f;
            float d = (a < 0 ? -a : a) + (b < 0 ? -b : b);
            if (d < best) { best = d; c = s_pts[i].c; }
        }
        if ((x * 3 + y) % 22 < 2 && (y / 7 + x / 9) % 3 == 0) c += 4;
        return c;
    }
    default: return 0;
    }
}

/* ---- pillars: one margin, composed for a country and a layout ---- */
enum { L_FULL, L_BATTLE, L_MAP, L_COUNT };
/* Plates of each layout as HD rows [y0, y1); L_BATTLE has the panel's cream line between. */
static const int s_plates[L_COUNT][2][2] = {
    [L_FULL]   = { { 0, RH }, { 0, 0 } },
    [L_BATTLE] = { { 0, 182 * RS }, { 184 * RS, RH } },
    [L_MAP]    = { { 168 * RS, RH }, { 0, 0 } },
};
static uint32_t *s_pillar[N_COUNT][L_COUNT];    /* RW x RH, 0x00RRGGBB; 0xFF000000 = not drawn */
#define NOT_DRAWN 0xFF000000u

static uint32_t shade(Rgb c, float k)
{
    int r = (int)((float)c.r * k), g = (int)((float)c.g * k), b = (int)((float)c.b * k);
    if (r > 255) r = 255;
    if (g > 255) g = 255;
    if (b > 255) b = 255;
    return (uint32_t)r << 16 | (uint32_t)g << 8 | (uint32_t)b;
}
static void rivet(uint32_t *img, int cx, int cy, int y0, int y1)
{
    for (int yy = -6; yy <= 6; yy++) for (int xx = -6; xx <= 6; xx++) {
        int rr = xx * xx + yy * yy, x = cx + xx, y = cy + yy;
        if (rr > 36 || y < y0 || y >= y1 || x < 20 || x >= RW) continue;
        uint32_t c = img[y * RW + x];
        float k = rr <= 12 && xx + yy < 0 ? 1.5f : rr > 20 ? 0.55f : 0.95f;
        Rgb p = { (uint8_t)(c >> 16), (uint8_t)(c >> 8), (uint8_t)c };
        img[y * RW + x] = shade(p, k);
    }
}
static const uint32_t *pillar(int nation, int layout, int width)
{
    /* the plate's outer edge follows the margin's width: one image per width in use */
    static int made_width;
    if (made_width != width) {
        for (int n = 0; n < N_COUNT; n++) for (int l = 0; l < L_COUNT; l++) { free(s_pillar[n][l]); s_pillar[n][l] = NULL; }
        made_width = width;
    }
    if (s_pillar[nation][layout]) return s_pillar[nation][layout];
    uint32_t *img = malloc(sizeof(uint32_t) * RW * RH);
    if (!img) return NULL;
    for (int i = 0; i < RW * RH; i++) img[i] = NOT_DRAWN;
    const Pattern *p = &s_pattern[nation];
    pattern_begin(p);
    for (int k = 0; k < 2; k++) {
        int y0 = s_plates[layout][k][0], y1 = s_plates[layout][k][1];
        for (int y = y0; y < y1; y++) for (int d = 0; d < width; d++) {
            uint32_t c;
            if (d < 8) c = shade(CREAM, 1);
            else if (d < 16) c = shade(MID, 1);
            else if (d < 20) c = shade(BLACK, 1);
            else {
                int i = pattern_at(p, d & ~1, y & ~1);          /* 2 px blocks */
                Rgb col = i == 3 ? (Rgb){ 24, 22, 18 } : p->col[i & 3];
                float f = i >= 4 ? 0.78f : 1.0f;
                f *= 1.0f + (float)((int)(((unsigned)(d / 4) * 73856093u ^ (unsigned)(y / 4) * 19349663u) % 7u) - 3) * 0.012f;
                if (d < 24 || y < y0 + 4) f *= 1.22f;           /* bevel: light from the top left */
                if (d >= width - 4 || y >= y1 - 4) f *= 0.6f;
                c = shade(col, f);
            }
            img[y * RW + d] = c;
        }
        if (y1 - y0 < 100) continue;
        for (int cy = y0 + 36; ; cy += 180) {                   /* rivets, the last pair at the bottom */
            if (cy > y1 - 36 - 90) cy = y1 - 36;
            rivet(img, 40, cy, y0, y1);
            rivet(img, width - 22, cy, y0, y1);
            if (cy == y1 - 36) break;
        }
    }
    if (layout == L_BATTLE)
        for (int y = 182 * RS; y < 184 * RS; y++) for (int d = 0; d < width; d++) img[y * RW + d] = shade(CREAM, 1);
    return s_pillar[nation][layout] = img;
}

/* ---- what to show ---- */
static int s_enabled = -1;
static int s_show, s_layout, s_left, s_right, s_bright;     /* state of the frame being drawn */

static uint32_t be32(unsigned a) { return (uint32_t)g_ram[a] << 24 | (uint32_t)g_ram[a + 1] << 16 | (uint32_t)g_ram[a + 2] << 8 | g_ram[a + 3]; }

/* Country of army 0–7: its name (record +$10) looked up in the ROM's name table. The names in
 * RAM follow the language in use, like the table (translation-rom.md). */
static int army_nation(unsigned army)
{
    const uint8_t *name = &g_ram[RAM_ARMIES + (army & 7u) * 0x20u + 0x10u];
    for (int i = 1; i < ARMY_NAMES; i++)
        if (!memcmp(name, &g_rom[ROM_ARMY_NAMES + (unsigned)i * 9u + 1u], 8)) return s_army_nation[i];
    return N_MINOR;
}
/* Army of the unit a battle record points to, or -1. */
static int battle_army(unsigned rec)
{
    uint32_t p = be32(rec + 8);
    if (p < 0xFFFFB000u || p >= 0xFFFFC800u) return -1;
    return g_ram[(p & 0xFFFFu) + 0x0Fu] & 7;
}
/* Mean screen x of the objects of a side ($40-byte records from base, x + 128 as the high word at
 * +$10), or -1000 when the side has none. */
#define BATTLE_OBJECTS 10
static int side_x(unsigned base)
{
    int sum = 0, n = 0;
    for (unsigned i = 0; i < BATTLE_OBJECTS; i++) {
        const uint8_t *o = &g_ram[base + i * 0x40u];
        int used = 0;
        for (int k = 0; k < 0x40 && !used; k++) used = o[k] != 0;
        if (!used) continue;
        sum += (int16_t)(o[0x10] << 8 | o[0x11]) - 128;
        n++;
    }
    return n ? sum / n : -1000;
}
/* Brightness 0–256 of the screen: the brightest colour component in CRAM. The game fades by
 * scaling its palette, so the frame fades with it. */
static int screen_brightness(const GVDP *v)
{
    if (!gvdp_display_enabled(v)) return 0;
    unsigned m = 0;
    for (int i = 0; i < GVDP_CRAM_ENTRIES; i++) {
        unsigned c = v->cram[i];
        for (int k = 0; k < 3; k++, c >>= 3) if ((c & 7u) > m) m = c & 7u;
    }
    return (int)(m * 256u / 7u);
}
static void frame_state(const GVDP *v)
{
    unsigned screen = g_ram[RAM_SCREEN];
    s_bright = screen_brightness(v);
    s_layout = ad_mapzoom_active() ? L_MAP : L_FULL;
    s_show = 1;
    /* No scenario loaded: V-int mode 6 is the intro before the first menu (no frame) and the
     * campaign briefing after it (the country of army 0, the player's); menus are plain. */
    static int s_menu_seen;
    if (!be32(RAM_ARMY_PTR)) {
        int text_screen = g_ram[RAM_VINT_MODE] == 6;
        if (!text_screen) s_menu_seen = 1;
        s_show = !text_screen || s_menu_seen;
        s_left = s_right = text_screen ? army_nation(0) : N_MINOR;
        return;
    }
    s_left = s_right = army_nation(g_ram[RAM_ARMY]);
    /* Battle: $FFD060 is the unit that acts, $FFD080 its target; their objects are the blocks
     * from $FFD100 / $FFD380. Who stands where is read once, on the first battle frame, from
     * where the objects start: in the 47 recorded battles the attacker's came in from the right
     * (x 290–530), the defender's from the left (below 50); a side without objects (a ranged
     * attack shows only its target) is placed by its own objects. The countries are kept: $FFCD04
     * and the V-int mode leave their battle values for single frames while the battle runs (the
     * text routine borrows $FFCD04), so the battle only counts as over after BATTLE_HOLD frames
     * without them (the screen is black by then). */
    enum { BATTLE_HOLD = 12 };
    static int in_battle, away, bl, br;
    if ((screen == 0x46 || screen == 0x66) && g_ram[RAM_VINT_MODE] == 4) {
        away = 0;
        if (!in_battle) {
            int a = battle_army(RAM_BATTLE_A), d = battle_army(RAM_BATTLE_D);
            int ax = side_x(RAM_OBJECTS_A), dx = side_x(RAM_OBJECTS_D);
            if (a >= 0 && d >= 0 && (ax > -1000 || dx > -1000)) {
                int a_left = ax > -1000 && dx > -1000 ? ax < dx
                           : ax > -1000 ? ax < 160 : dx >= 160;
                bl = army_nation((unsigned)(a_left ? a : d));
                br = army_nation((unsigned)(a_left ? d : a));
                in_battle = 1;
                fprintf(stderr, "[ADS] Battle: attacker army %d (x %d) %s, defender army %d (x %d)\n",
                        a, ax, a_left ? "left" : "right", d, dx);
            }
        }
    } else if (++away > BATTLE_HOLD) in_battle = 0;
    if (in_battle) { s_left = bl; s_right = br; s_layout = L_BATTLE; }
}

static void margin_hook(void *user, const GVDP *v, int line, int sub, int scale, int px,
                        uint32_t *left, uint32_t *right)
{
    (void)user;
    if (line == 0 && sub == 0) frame_state(v);
    if (!s_show || s_bright <= 0 || line < 0 || line >= 224 || scale < 1) return;
    int width = px * RS / scale;                    /* margin in reference pixels */
    if (width > RW) width = RW;
    if (width < 40) return;
    const uint32_t *pl = pillar(s_left, s_layout, width), *pr = pillar(s_right, s_layout, width);
    if (!pl || !pr) return;
    int y = (line * scale + sub) * RS / scale;
    pl += y * RW; pr += y * RW;
    unsigned k = (unsigned)s_bright;
    for (int x = 0; x < px; x++) {
        int d = x * RS / scale;                     /* distance from the picture's edge */
        uint32_t a = pl[d], b = pr[d];
        if (a != NOT_DRAWN)
            left[px - 1 - x] = 0xFF000000u | ((a >> 16 & 255u) * k >> 8) << 16 | ((a >> 8 & 255u) * k >> 8) << 8 | ((a & 255u) * k >> 8);
        if (b != NOT_DRAWN)
            right[x] = 0xFF000000u | ((b >> 16 & 255u) * k >> 8) << 16 | ((b >> 8 & 255u) * k >> 8) << 8 | ((b & 255u) * k >> 8);
    }
}

/* Called every V-int (ad_spec.c): installs the hook on first use. */
void ad_frame_vint(void)
{
    if (s_enabled >= 0) return;
    const char *e = getenv("AD_FRAME");
    s_enabled = e ? atoi(e) > 0 : 1;
    if (memcmp(&g_rom[0x100], "SEGA", 4) != 0) s_enabled = 0;
    if (s_enabled) genesis_hd_set_margin_argb_hook(margin_hook, NULL);
    fprintf(stderr, "[ADS] Camouflage frame in the 16:9 margins: %s\n", s_enabled ? "on" : "off");
}
