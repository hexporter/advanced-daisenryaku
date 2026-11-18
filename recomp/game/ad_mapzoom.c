/*
 * ad_mapzoom.c – zoomed-out hex map in the HD frame (docs/notes/map.md).
 *
 * The game draws only the hexes around its view into the VDP planes. In zoomed mode the HD
 * frame shows the map area (screen x 0–319, y 8–167) with twice as many hexes in each
 * direction (half size), centred on the game's view, redrawn the way the game would from:
 *   RAM  $FFA000 terrain, $FF7000 fog / movement range flags, $FFB000 units, $FFCD1E–$CD21 view
 *   ROM  hex block tables (model of $012EDA), unit graphics (model of $012B3A)
 *   VRAM terrain tile patterns (the map screen has the whole set loaded), CRAM via the palette
 * Same rules as tools/mapzoom.py, which was checked pixel-exact against the game's own screen.
 *
 * Hooks into the HD layer (framework patch 0008): the planes of a line in the viewport are
 * replaced by the zoomed map; the cursor and unit sprites (map-anchored) are left out of the
 * HD frame and drawn into the zoomed map instead; all other sprites (menus, windows) stay, and
 * are mirrored to the other side of the screen when they would cover the cursor's hex.
 * Presentation only – nothing the game reads changes, the 1x frame is untouched.
 *
 * F9 (or System menu → System → "HD map") toggles; the choice is kept in ad-port.ini
 * (hd_map = on|off, on by default); AD_MAP_ZOOM=0|1 overrides it for one launch. Active only while the hex map is on screen
 * (hex stagger in plane B's hscroll, see on_map_screen and map.md).
 */
#include "genesis_vdp.h"

#include <SDL2/SDL.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern uint8_t g_rom[0x400000];
extern uint8_t g_ram[0x010000];

/* ---- ROM tables (docs/notes/map.md) ---- */
#define ROM_SEASON_TABLES  0x013214u
#define ROM_CLASS_MASKS    0x0130FCu
#define ROM_NBR_ODD        0x0130D8u
#define ROM_NBR_EVEN       0x0130E4u
#define ROM_PLAIN_BLOCKS   0x038332u
#define ROM_JOIN_BLOCKS    0x04342Au
#define ROM_UNIT_TYPES     0x02B1F2u
#define ROM_UNIT_GFX       0x05B42Au
#define ROM_UNIT_PATTERNS  0x04852Au
#define ROM_UNIT_MASK      0x039F5Eu
#define ROM_UNIT_OVER      0x039A1Eu
#define ROM_SPRITE_TERRAIN 0x012AF4u

/* ---- RAM ---- */
#define RAM_FLAGS    0x7000u
#define RAM_TERRAIN  0xA000u
#define RAM_UNITS    0xB000u
#define RAM_GRID_OFF 0xCC25u
#define RAM_SEASON   0xCDABu
#define RAM_VIEW_X   0xCD20u
#define RAM_VIEW_Y   0xCD21u

/* Viewport on screen (1x) and the zoomed area in map pixels. */
#define VP_X 0
#define VP_Y 8
#define VP_W 320
#define VP_H 160
#define ZH (VP_H * 2)
/* Width of the area: the viewport plus the HD frame's side margins (framework patch 0010,
 * GENESIS_HD_MARGIN; 39 px each side = 16:9), 2 map pixels per screen pixel. */
#define ZWMAX ((VP_W + 2 * GVDP_HD_MAX_MARGIN) * 2)
static int s_margin;           /* side margin in screen pixels (1x), 0 = none */
static int s_zw = VP_W * 2;
#define ZW s_zw

static int s_enabled = -1;     /* F9 / AD_MAP_ZOOM */
static int s_active;           /* enabled and on the map screen, this frame */
static int s_last_line = 1 << 30;
static int s_zx0, s_zy0;       /* map pixel of the zoomed area's top-left */

/* Zoomed map, one byte per map pixel in the HD plane encoding
 * (priority<<7 | opaque<<6 | palette<<4 | colour). */
static uint8_t s_zb[ZH][ZWMAX];   /* terrain (plane B) */
static uint8_t s_za[ZH][ZWMAX];   /* grid, units, cursor (plane A, sprites merged on top) */
static int s_ui_dx;            /* sideways shift of menu/window sprites this frame */
static int s_dbg[10];          /* what build() used this frame, for ad_record.c */
static int s_spr_view[4];      /* view ($CD20, $CD21, $CD14, $CD16) of the game's last frame step */
static int s_spr_applied[4];   /* the view that belongs to the sprite table now in VRAM */

static unsigned rw(uint32_t a) { return (unsigned)g_rom[a] << 8 | g_rom[a + 1]; }
static uint32_t rl(uint32_t a) { return (uint32_t)rw(a) << 16 | rw(a + 2); }
static int16_t  rs(uint32_t a) { return (int16_t)rw(a); }
static unsigned terr(unsigned i) { return g_ram[RAM_TERRAIN + (i & 0xFFFu)]; }

static uint32_t class_mask(unsigned code)
{
    uint32_t d = rl(ROM_CLASS_MASKS + code * 4u);
    return (d & 0xFF00FFFFu) | ((d >> 24) << 16);
}

static void nbrs(unsigned y, int out[6])
{
    uint32_t base = (y & 1u) ? ROM_NBR_ODD : ROM_NBR_EVEN;
    for (int k = 0; k < 6; k++) out[k] = rs(base + 2u * (unsigned)k);
}

/* Model of $012EDA: 6 plane B words and 6 plane A words, TL TM TR BL BM BR. */
static void hex_words(unsigned x, unsigned y, uint16_t b[6], uint16_t a[6])
{
    unsigned idx = y * 64u + x, code = terr(idx) & 0x7Fu;
    unsigned g = g_rom[rl(ROM_SEASON_TABLES + g_ram[RAM_SEASON] * 4u) + code];
    uint32_t cls = 0, blk;
    int off[6];
    nbrs(y, off);
    if (g & 0x80u) {
        cls = class_mask(code);
        unsigned n = 0;
        for (int k = 0; k < 6; k++) {
            n = (n << 1) & 0xFFFFu;
            if (!(cls & class_mask(terr(idx + (unsigned)off[k]) & 0x7Fu))) n |= 1u;
        }
        blk = ROM_JOIN_BLOCKS + (g & 0x7Fu) * 0x300u + n * 12u;
    } else {
        blk = ROM_PLAIN_BLOCKS + g * 12u;
    }
    for (int k = 0; k < 6; k++) b[k] = (uint16_t)rw(blk + 2u * (unsigned)k);
    unsigned d0 = (g_ram[RAM_FLAGS + idx] & 0x40u) ? 0x8000u : 0u;
    if (cls & 0x80000000u) {
        uint32_t m = (cls & 0x20000000u) ? 0x60300u : 0x80002u;
        unsigned side = 0;
        for (int k = 0; k < 3; k++)
            if (m & class_mask(terr(idx + (unsigned)off[k]) & 0x7Fu)) { side = 2u - (unsigned)k; break; }
        d0 += side * 6u + ((cls & 0x20000000u) ? 0x25E3u : 0x25BFu);
        if (cls & 0x10000000u) d0 += 0x12u;
    } else if (g_ram[RAM_GRID_OFF]) {
        for (int k = 0; k < 6; k++) a[k] = (uint16_t)d0;
        return;
    } else {
        d0 += 0x3C8u;
    }
    static const unsigned add[6] = { 0, 2, 4, 1, 3, 5 };
    for (int k = 0; k < 6; k++) a[k] = (uint16_t)(d0 + add[k]);
}

/* Model of $012B3A: the 6 composed tiles of a unit in plane order, palette line. */
static unsigned unit_tiles(const uint8_t *r, uint8_t tiles[6][32])
{
    unsigned typ = (unsigned)r[2] << 8 | r[3];
    unsigned gfx = rw(ROM_UNIT_TYPES + typ * 0x22u + 0x14u);
    unsigned v = ((r[4] & 0x80u) ? 1u : 0u) + ((r[4] & 0x20u) ? 2u : 0u);
    int nogrid = g_ram[RAM_GRID_OFF] != 0;
    static const unsigned col_major[6] = { 0, 2, 4, 1, 3, 5 };  /* plane position -> k */
    for (int p = 0; p < 6; p++) {
        unsigned k = col_major[p];
        uint32_t src = ROM_UNIT_PATTERNS + rw(ROM_UNIT_GFX + gfx * 12u + 2u * k) * 32u;
        if (nogrid && v == 0) { memcpy(tiles[p], &g_rom[src], 32); continue; }
        unsigned vv = nogrid ? v + 3u : v;
        const uint8_t *m = &g_rom[ROM_UNIT_MASK + vv * 0xC0u + 32u * k];
        const uint8_t *o = &g_rom[ROM_UNIT_OVER + vv * 0xC0u + 32u * k];
        for (int i = 0; i < 32; i++) tiles[p][i] = (uint8_t)((g_rom[src + (unsigned)i] & m[i]) | o[i]);
    }
    return r[0x0F] >> 1;
}

/* Put one 8x8 tile at map pixel (px, py) into a layer. pat == NULL: VRAM tile of `word`. */
static void put_tile(uint8_t (*layer)[ZWMAX], const GVDP *v, int px, int py, unsigned word,
                     const uint8_t *pat, int over)
{
    int x0 = px - s_zx0, y0 = py - s_zy0;
    if (x0 <= -8 || y0 <= -8 || x0 >= ZW || y0 >= ZH) return;
    unsigned t = word & 0x7FFu, pal = (word >> 13) & 3u, prio = word >> 15;
    int hf = (word & 0x800u) != 0, vf = (word & 0x1000u) != 0;
    for (int fy = 0; fy < 8; fy++) {
        int y = y0 + fy;
        if (y < 0 || y >= ZH) continue;
        int sy = vf ? 7 - fy : fy;
        for (int fx = 0; fx < 8; fx++) {
            int x = x0 + fx;
            if (x < 0 || x >= ZW) continue;
            int sx = hf ? 7 - fx : fx;
            uint8_t byte = pat ? pat[sy * 4 + sx / 2] : v->vram[(t * 32u + (unsigned)sy * 4u + (unsigned)sx / 2u) & 0xFFFFu];
            unsigned n = (sx & 1) ? byte & 15u : byte >> 4;
            if (over) {   /* sprite-like: only opaque pixels, keep the plane priority bit */
                if (n) layer[y][x] = (uint8_t)((layer[y][x] & 0x80u) | (prio << 7) | 0x40u | (pal << 4) | n);
            } else {
                layer[y][x] = (uint8_t)((prio << 7) | (n ? 0x40u : 0u) | (pal << 4) | n);
            }
        }
    }
}

static void hexpos(unsigned x, unsigned y, int *px, int *py)
{
    *px = 24 * (int)x + ((y & 1u) ? 12 : 0);
    *py = 16 * (int)y;
}

/* Sprites in the map area: the cursor (4x4, tile $001) and 3x2 unit sprites belong to the map;
 * the 4x4 columns of tile $011 at the screen edges shade the border; the rest are menus and
 * windows (command menu, target info, ...). */
static int map_sprite(unsigned size, unsigned attr)
{
    unsigned sz = size & 0x0Fu, tile = attr & 0x7FFu;
    return (sz == 0x0Fu && tile == 0x001u) || sz == 0x09u;
}
static int edge_sprite(unsigned attr) { return (attr & 0x7FFu) == 0x011u; }

/* The game places its menus for its own view (command menu always at x 36), so in the zoomed
 * map they can cover the cursor's hex. Then mirror the boxes to the other side of the screen. */
static void place_ui(const GVDP *v, int cur_x, int cur_y, int cur_w, int cur_h)
{
    unsigned sat = (unsigned)(v->reg[5] & 0x7Fu) << 9;
    int x0 = 1 << 20, y0 = 1 << 20, x1 = -(1 << 20), y1 = -(1 << 20), link = 0;
    s_ui_dx = 0;
    for (int n = 0; n < 80; n++) {
        unsigned e = sat + (unsigned)link * 8u;
        int y = (int)(((unsigned)v->vram[e & 0xFFFFu] << 8 | v->vram[(e + 1) & 0xFFFFu]) & 0x3FFu) - 128;
        unsigned sz = v->vram[(e + 2) & 0xFFFFu];
        int next = v->vram[(e + 3) & 0xFFFFu] & 0x7F;
        unsigned attr = (unsigned)v->vram[(e + 4) & 0xFFFFu] << 8 | v->vram[(e + 5) & 0xFFFFu];
        int x = (int)((((unsigned)v->vram[(e + 6) & 0xFFFFu] << 8 | v->vram[(e + 7) & 0xFFFFu]) & 0x1FFu)) - 128;
        int w = (int)(((sz >> 2) & 3u) + 1u) * 8, h = (int)((sz & 3u) + 1u) * 8;
        if (y < VP_Y + VP_H && y + h > VP_Y && x < VP_X + VP_W && x + w > VP_X &&
            !map_sprite(sz, attr) && !edge_sprite(attr)) {
            if (x < x0) x0 = x;
            if (y < y0) y0 = y;
            if (x + w > x1) x1 = x + w;
            if (y + h > y1) y1 = y + h;
        }
        if (next == 0) break;
        link = next;
    }
    if (x1 < x0) return;
#define OVERLAP(ax0, ax1) ((ax0) < cur_x + cur_w && (ax1) > cur_x && y0 < cur_y + cur_h && y1 > cur_y)
    if (!OVERLAP(x0, x1)) return;
    int dx = (VP_X + VP_W - x1) - (x0 - VP_X);      /* mirror the boxes' extent */
    if (!OVERLAP(x0 + dx, x1 + dx)) s_ui_dx = dx;
#undef OVERLAP
}

/* Map-anchored sprites (cursor, unit sprites incl. the unit gliding along its path while it
 * moves) are copied from the sprite table into the zoomed map at their map position:
 * map = screen + (24*X0 - 10, 16*Y0 - 8) + 8*($CD14, $CD16) (fine scroll, as in $009CD8).
 * Returns 1 and the cursor's map position (sprite top-left) when the cursor sprite is shown. */
static int draw_map_sprites(const GVDP *v, unsigned X0, unsigned Y0, int moving, int *cur_px, int *cur_py)
{
    unsigned sat = (unsigned)(v->reg[5] & 0x7Fu) << 9;
    /* The sprite table is built by the game's frame step: use the view of that step, not today's
     * (a skipped scroll moves the view for a few frames while the table stands still, and even a
     * normal scroll is a frame ahead of it; map.md). */
    (void)X0; (void)Y0;
    /* The table reaches VRAM later than the step that built it (after a scroll the V-int copies
     * the planes first), so that view applies only once the table has really changed. */
    static uint8_t last_sat[0x280];
    int changed = 0;
    for (unsigned i = 0; i < sizeof last_sat; i++) {
        uint8_t b = v->vram[(sat + i) & 0xFFFFu];
        if (b != last_sat[i]) { last_sat[i] = b; changed = 1; }
    }
    if (changed) memcpy(s_spr_applied, s_spr_view, sizeof s_spr_applied);
    int offx = 24 * s_spr_applied[0] - 10 + 8 * s_spr_applied[2];
    int offy = 16 * s_spr_applied[1] - 8 + 8 * s_spr_applied[3];
    int list[80], count = 0, link = 0, cursor = 0;
    for (int n = 0; n < 80; n++) {                  /* link order = front to back */
        list[count++] = link;
        int next = v->vram[(sat + (unsigned)link * 8u + 3u) & 0xFFFFu] & 0x7F;
        if (next == 0) break;
        link = next;
    }
    for (int i = count - 1; i >= 0; i--) {          /* draw back to front */
        unsigned e = sat + (unsigned)list[i] * 8u;
        int y = (int)(((unsigned)v->vram[e & 0xFFFFu] << 8 | v->vram[(e + 1) & 0xFFFFu]) & 0x3FFu) - 128;
        unsigned sz = v->vram[(e + 2) & 0xFFFFu];
        unsigned attr = (unsigned)v->vram[(e + 4) & 0xFFFFu] << 8 | v->vram[(e + 5) & 0xFFFFu];
        int x = (int)((((unsigned)v->vram[(e + 6) & 0xFFFFu] << 8 | v->vram[(e + 7) & 0xFFFFu]) & 0x1FFu)) - 128;
        if (!map_sprite(sz, attr) || y >= VP_Y + VP_H || y < -32 || x < -32 || x >= VP_X + VP_W) continue;
        /* 3x2 unit sprites (tiles $094+) are drawn from RAM already unless a unit is moving.
         * Other 3x2 sprites are effects in a hex and are always copied: the puff of a ranged
         * shot that misses is tile $021 at the target hex (map.md). */
        if ((sz & 0x0Fu) == 0x09u && !moving && (attr & 0x7FFu) >= 0x094u) continue;
        int mx = x + offx, my = y + offy;
        if ((sz & 0x0Fu) == 0x0Fu) {
            /* The cursor sprite follows $CD1E/$CD20 a frame late when the view scrolls, so the
             * copy landed one hex back. Place it from RAM like $009CD8:
             * map = hex position - (8, 8); the sprite only says whether it is shown. */
            hexpos((unsigned)(g_ram[0xCD1E] + g_ram[RAM_VIEW_X]) & 63u,
                   (unsigned)(g_ram[0xCD1F] + g_ram[RAM_VIEW_Y]) & 63u, &mx, &my);
            mx -= 8;
            my -= 8;
            cursor = 1;
            *cur_px = mx;
            *cur_py = my;
        }
        unsigned hs = ((sz >> 2) & 3u) + 1u, vs = (sz & 3u) + 1u;
        for (unsigned cx = 0; cx < hs; cx++)
            for (unsigned cy = 0; cy < vs; cy++)
                put_tile(s_za, v, mx + 8 * (int)cx, my + 8 * (int)cy,
                         (attr & 0xE000u) | ((attr + cx * vs + cy) & 0x7FFu), NULL, 1);
    }
    return cursor;
}

/* Camera of the zoomed area. The game scrolls its view in whole hex columns/rows, several at
 * once and unevenly (5 columns in ~15 frames: $CD20 +1 +2 +1 +1, fine scroll $CD14 in between),
 * so following it jumps. The zoomed area (twice the view) moves only when
 * the game's view comes within a margin of its edge, and glides there: a quarter of the way
 * per frame. */
#define CAM_MX 48
#define CAM_MY 32
/* The border columns (sprite tile $011) cover 10 px of the screen on each side = 20 map px of
 * the zoomed area. The area may run that far past the map's left and right bounds, so that the
 * outermost hex column is not under the border (seen on FrAfrica; map.md). With
 * side margins the border columns are left out instead (sprite_hook) and the bounds are exact. */
#define EDGE_MX 20
static int s_cam_x, s_cam_y, s_cam_valid;

static int glide(int cur, int target)
{
    int d = target - cur;
    if (d > ZW * 2 || d < -ZW * 2) return target;     /* far jump (new map): no glide */
    return cur + (d > 0 ? (d + 3) / 4 : -((-d + 3) / 4));
}

static void build(const GVDP *v)
{
    unsigned X0 = g_ram[RAM_VIEW_X], Y0 = g_ram[RAM_VIEW_Y];
    int margin = gvdp_hd_margin();
    if (margin != s_margin) {                         /* area width changed: start centred again */
        s_margin = margin;
        s_zw = (VP_W + 2 * margin) * 2;
        s_cam_valid = 0;
    }
    int edge = s_margin ? 0 : EDGE_MX;
    /* screen = map - (24*X0 - 10, 16*Y0 - 8) - 8*fine scroll (map.md, $009CD8) */
    int gx = 24 * (int)X0 - 10 + 8 * (int16_t)(g_ram[0xCD14] << 8 | g_ram[0xCD15]) + VP_X;
    int gy = 16 * (int)Y0 - 8 + 8 * (int16_t)(g_ram[0xCD16] << 8 | g_ram[0xCD17]) + VP_Y;
    if (!s_cam_valid) {                               /* first frame: centred on the view */
        s_cam_x = gx + VP_W / 2 - ZW / 2;
        s_cam_y = gy + VP_H / 2 - ZH / 2;
    }
    s_zx0 = s_cam_x;
    s_zy0 = s_cam_y;
    if (gx - CAM_MX < s_zx0) s_zx0 = gx - CAM_MX;
    if (gx + VP_W + CAM_MX > s_zx0 + ZW) s_zx0 = gx + VP_W + CAM_MX - ZW;
    if (gy - CAM_MY < s_zy0) s_zy0 = gy - CAM_MY;
    if (gy + VP_H + CAM_MY > s_zy0 + ZH) s_zy0 = gy + VP_H + CAM_MY - ZH;
    /* keep the area on the map: clamp to its bounds, centre a map smaller than the area */
    int mx0 = 64, my0 = 64, mx1 = -1, my1 = -1;
    for (int i = 0; i < 4096; i++) {
        if (terr((unsigned)i) & 0x80u) continue;
        int x = i & 63, y = i >> 6;
        if (x < mx0) mx0 = x;
        if (x > mx1) mx1 = x;
        if (y < my0) my0 = y;
        if (y > my1) my1 = y;
    }
    if (mx1 >= 0) {
        int px0 = 24 * mx0 - edge, px1 = 24 * mx1 + 36 + edge;
        int py0 = 16 * my0, py1 = 16 * my1 + 16;
        if (px1 - px0 <= ZW) s_zx0 = (px0 + px1) / 2 - ZW / 2;
        else if (s_zx0 < px0) s_zx0 = px0;
        else if (s_zx0 > px1 - ZW) s_zx0 = px1 - ZW;
        if (py1 - py0 <= ZH) s_zy0 = (py0 + py1) / 2 - ZH / 2;
        else if (s_zy0 < py0) s_zy0 = py0;
        else if (s_zy0 > py1 - ZH) s_zy0 = py1 - ZH;
    }
    /* s_zx0/s_zy0 = where the camera should be; glide there */
    if (s_cam_valid) {
        s_zx0 = glide(s_cam_x, s_zx0);
        s_zy0 = glide(s_cam_y, s_zy0);
    }
    s_cam_x = s_zx0;
    s_cam_y = s_zy0;
    s_cam_valid = 1;
    memset(s_za, 0, sizeof s_za);
    memset(s_zb, 0, sizeof s_zb);

    static int16_t unit_at[4096];
    memset(unit_at, 0xFF, sizeof unit_at);
    int moving = 0;
    for (int n = 0; n < 256; n++) {
        const uint8_t *r = &g_ram[RAM_UNITS + (unsigned)n * 0x18u];
        /* Y + $80 (Y <= 63) only; $FF = empty, $FE = other non-map records (always there) */
        if ((r[0] & 0xC0u) == 0x80u) moving = 1;
        /* $012D4A; Y bit 7 = unit on its way (moving, shown as a sprite) */
        if ((r[0] & 0x80u) || (r[4] & 0x10u) || (r[0x10] & 0x80u)) continue;
        unit_at[(r[0] & 63u) * 64u + (r[1] & 63u)] = (int16_t)n;
    }
    int ymin = s_zy0 / 16 - 1, ymax = (s_zy0 + ZH) / 16 + 1;
    int xmin = s_zx0 / 24 - 1, xmax = (s_zx0 + ZW) / 24 + 1;
    if (ymin < 0) ymin = 0;
    if (xmin < 0) xmin = 0;
    if (ymax > 63) ymax = 63;
    if (xmax > 63) xmax = 63;
    uint8_t tiles[6][32];
    for (int y = ymin; y <= ymax; y++) {
        for (int x = xmin; x <= xmax; x++) {
            unsigned idx = (unsigned)y * 64u + (unsigned)x;
            if (terr(idx) & 0x80u) continue;
            uint16_t b[6], a[6];
            int px, py;
            hexpos((unsigned)x, (unsigned)y, &px, &py);
            hex_words((unsigned)x, (unsigned)y, b, a);
            for (int k = 0; k < 6; k++)
                put_tile(s_zb, v, px + 8 * (k % 3), py + 8 * (k / 3), b[k], NULL, 0);
            int n = unit_at[idx];
            if (n < 0) {
                for (int k = 0; k < 6; k++)
                    put_tile(s_za, v, px + 8 * (k % 3), py + 8 * (k / 3), a[k], NULL, 0);
                continue;
            }
            unsigned pal = unit_tiles(&g_ram[RAM_UNITS + (unsigned)n * 0x18u], tiles);
            unsigned vis = (g_ram[RAM_FLAGS + idx] & 0x40u) ? 0x8000u : 0u;
            int as_sprite = g_rom[ROM_SPRITE_TERRAIN + (terr(idx) & 0x7Fu)] != 0;
            for (int k = 0; k < 6; k++) {
                int tx = px + 8 * (k % 3), ty = py + 8 * (k / 3);
                if (as_sprite) {
                    put_tile(s_za, v, tx, ty, a[k], NULL, 0);
                    put_tile(s_za, v, tx, ty, vis | (pal << 13), tiles[k], 1);
                } else {
                    put_tile(s_za, v, tx, ty, vis | (pal << 13), tiles[k], 0);
                }
            }
        }
    }
    int cpx, cpy;
    int has_cursor = draw_map_sprites(v, X0, Y0, moving, &cpx, &cpy);
    s_dbg[0] = (int)X0; s_dbg[1] = (int)Y0;
    s_dbg[2] = (int16_t)(g_ram[0xCD14] << 8 | g_ram[0xCD15]);
    s_dbg[3] = (int16_t)(g_ram[0xCD16] << 8 | g_ram[0xCD17]);
    s_dbg[4] = s_zx0; s_dbg[5] = s_zy0;
    s_dbg[6] = has_cursor ? cpx : -1; s_dbg[7] = has_cursor ? cpy : -1;
    s_dbg[8] = s_spr_applied[0]; s_dbg[9] = s_spr_applied[2];
    if (has_cursor)
        /* the cursor's hex (24x16 at +8,+8 in its 32x32 sprite) on screen: 2 map px per 1x px;
         * the area starts s_margin screen px left of the viewport */
        place_ui(v, VP_X - s_margin + (cpx + 8 - s_zx0) / 2, VP_Y + (cpy + 8 - s_zy0) / 2, 12, 8);
}

/* The hex map is on screen when plane B's per-cell horizontal scroll shows the hex stagger:
 * two values 12 px apart (e.g. -530/-542), non-zero, in pairs of cell rows (x x y y x x).
 * All other screens (title, menus, turn start, battle) have 0 there; the map keeps it until the
 * battle screen replaces it – unlike $FF0110 / $FFCDA3, which change ~6 frames earlier while the
 * map is still shown (attack, missed shot). The pairs start at cell row 1
 * or, for a frame when the view moves by a hex row, at cell row 2 (scrolling up and down
 * flashed the original map), so both phases count. map.md. */
static int on_map_screen(const GVDP *v)
{
    if ((v->reg[0x0B] & 3u) != 2u) return 0;             /* per-cell hscroll */
    unsigned hb = (unsigned)(v->reg[0x0D] & 0x3Fu) << 10;
    int h[6];
    for (int r = 0; r < 6; r++) {
        unsigned a = (hb + (unsigned)(8 + 8 * r) * 4u + 2u) & 0xFFFFu;   /* plane B, cell rows 1-6 */
        h[r] = (int)(((unsigned)v->vram[a] << 8 | v->vram[a + 1]) & 0x3FFu);
    }
    int lo = h[0], hi = h[0];
    for (int r = 0; r < 6; r++) {
        if (h[r] == 0) return 0;
        if (h[r] != lo && h[r] != hi) {
            if (lo != hi) return 0;                       /* a third value */
            if (h[r] < lo) lo = h[r]; else hi = h[r];
        }
    }
    int d = hi - lo;
    if (d != 12 && d != 0x3FF - 11) return 0;
    for (int r = 0; r + 2 < 6; r++)                       /* period 4: pairs, not single rows */
        if (h[r] == h[r + 2]) return 0;
    return 1;
}

static const GVDP *s_vdp;
static int s_since_hd;         /* V-ints since the last presented HD frame */

static void layer_hook(void *user, const GVDP *v, int line, unsigned S, int width,
                       uint8_t *a, uint8_t *b, int stride)
{
    (void)user;
    s_vdp = v;
    s_since_hd = 0;
    if (line < s_last_line) {          /* new frame */
        s_active = s_enabled > 0 && width >= VP_X + VP_W && on_map_screen(v);
        s_ui_dx = 0;
        if (s_active) build(v);
    }
    s_last_line = line;
    if (!s_active || line < VP_Y || line >= VP_Y + VP_H) return;
    for (unsigned r = 0; r < S; r++) {
        /* HD row -> zoomed map row: 2 map pixels per 1x pixel */
        int zy = (int)(((unsigned)(line - VP_Y) * S + r) * 2u / S);
        uint8_t *ra = a + (size_t)r * (size_t)stride, *rb = b + (size_t)r * (size_t)stride;
        for (unsigned hx = (unsigned)VP_X * S; hx < (unsigned)(VP_X + VP_W) * S; hx++) {
            unsigned zx = (unsigned)s_margin * 2u + (hx - (unsigned)VP_X * S) * 2u / S;
            ra[hx] = s_za[zy][zx];
            rb[hx] = s_zb[zy][zx];
        }
    }
}

/* Side margins of the HD frame (framework patch 0010): the zoomed map continues into them on
 * the map's lines; everywhere else they stay black. Called after layer_hook for the line. */
static int margin_hook(void *user, const GVDP *v, int line, unsigned S, int margin,
                       uint8_t *la, uint8_t *lb, uint8_t *ra, uint8_t *rb, int stride)
{
    (void)user; (void)v;
    if (!s_active || margin != s_margin || line < VP_Y || line >= VP_Y + VP_H) return 0;
    unsigned right0 = (unsigned)(s_margin + VP_W) * 2u;      /* area column of the right margin */
    for (unsigned r = 0; r < S; r++) {
        int zy = (int)(((unsigned)(line - VP_Y) * S + r) * 2u / S);
        size_t o = (size_t)r * (size_t)stride;
        for (unsigned hx = 0; hx < (unsigned)margin * S; hx++) {
            unsigned zx = hx * 2u / S;
            la[o + hx] = s_za[zy][zx];
            lb[o + hx] = s_zb[zy][zx];
            ra[o + hx] = s_za[zy][right0 + zx];
            rb[o + hx] = s_zb[zy][right0 + zx];
        }
    }
    return 1;
}

/* Map-anchored sprites are left out (drawn into the zoomed map instead): the cursor and units
 * shown as sprites (on overlay terrain, the unit being moved). Menus/windows may be mirrored. */
static int sprite_hook(void *user, int *x, int y, unsigned size, unsigned attr)
{
    (void)user;
    if (!s_active || y >= VP_Y + VP_H) return 0;
    if (map_sprite(size, attr)) return 1;
    if (s_margin && edge_sprite(attr)) return 1;      /* the map runs on past the border */
    if (s_ui_dx && !edge_sprite(attr)) *x += s_ui_dx;
    return 0;
}

/* For ad_record.c: the values of the last build; the VDP when the zoomed map is active. */
const GVDP *ad_mapzoom_state(int out[10])
{
    memcpy(out, s_dbg, sizeof s_dbg);
    return s_active ? s_vdp : NULL;
}

/* For ad_spec.c: skip the frame waits of the game's view scroll? While it scrolls (5 columns,
 * ~16 frames) the cursor does not advance, which the zoomed map shows as a stop
 * (map.md). Nothing of that scroll is visible in the zoom, so it is done within one
 * frame; game time, and with it the music (Z80), is not touched. AD_SCROLL_SKIP=0 turns it off.
 * s_active is only updated on presented HD frames: require a recent one (F10 turns HD off). */
int ad_mapzoom_frame_step(int in_scroll)
{
    static int skip = -1;
    if (skip < 0) {
        const char *e = getenv("AD_SCROLL_SKIP");
        skip = e ? atoi(e) != 0 : 1;
    }
    if (in_scroll && skip && s_active && s_since_hd <= 40) return 1;
    s_spr_view[0] = g_ram[RAM_VIEW_X];
    s_spr_view[1] = g_ram[RAM_VIEW_Y];
    s_spr_view[2] = (int16_t)(g_ram[0xCD14] << 8 | g_ram[0xCD15]);
    s_spr_view[3] = (int16_t)(g_ram[0xCD16] << 8 | g_ram[0xCD17]);
    return 0;
}

/* For ad_frame.c: is the zoomed map on screen (it fills the margins of lines 8–167)? */
int ad_mapzoom_active(void) { return s_active && s_since_hd <= 40; }

/* For the "HD map" row of the System settings screen (ad_spec.c). */
int ad_mapzoom_enabled(void) { return s_enabled > 0; }
const char *ad_port_setting(const char *key);           /* ad_lang.c */
void ad_port_store(const char *key, const char *value);

void ad_mapzoom_toggle(void)
{
    s_enabled = s_enabled > 0 ? 0 : 1;
    ad_port_store("hd_map", s_enabled ? "on" : "off");
    fprintf(stderr, "[ADS] Zoomed-out map: %s\n", s_enabled ? "on" : "off");
}

/* Called every V-int (ad_spec.c): F9 toggles, hooks installed on first use. */
void ad_mapzoom_vint(void)
{
    static int key_down;
    if (s_enabled < 0) {
        const char *e = getenv("AD_MAP_ZOOM"), *v = ad_port_setting("hd_map");
        s_enabled = e ? atoi(e) > 0 : !v || strcmp(v, "off") != 0;   /* on by default */
        if (memcmp(&g_rom[0x100], "SEGA", 4) != 0) { s_enabled = 0; return; }
        gvdp_hd_set_hooks(layer_hook, sprite_hook, NULL);
        gvdp_hd_set_margin_hook(margin_hook, NULL);
        fprintf(stderr, "[ADS] Zoomed-out map (HD frame): %s, F9 toggles\n", s_enabled ? "on" : "off");
    }
    const Uint8 *ks = SDL_GetKeyboardState(NULL);
    int down = ks && ks[SDL_SCANCODE_F9];
    if (down && !key_down) ad_mapzoom_toggle();
    key_down = down;
    s_since_hd++;
}
