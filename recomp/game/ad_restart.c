/*
 * ad_restart.c – "Restart": begin the campaign map in play again (docs/notes/campaign.md).
 *
 * Every map starts at $0085D4 (new game $0063B4/$0063BC, next map $008D52). At that point the
 * port copies the six RAM blocks the game itself saves (docs/notes/saving.md); "Restart" puts
 * them back and enters $0085D4 again. A campaign map cannot be loaded a second time instead:
 * the loader $006488 keeps the player's units, adds money and moves the date on.
 *
 * In the campaign the Record menu's third row "Give up" does nothing ($011860: tst.b $FFCC38,
 * beq → back into the menu). There the row reads "Restart" and opens the game's own
 * Cancel / Exec. dialog; standard mode keeps "Give up". No 68000 code is added: the row's text
 * pointer in the ROM image is swapped, and hooks steer the handler ($FFCC38 reads 1 for the
 * one tst, so the handler opens its dialog).
 *
 * A save keeps its map start: saving copies the snapshot into a companion record of the slot
 * (ad-mapstart.bin in the data folder, keyed by the slot's six checksums), loading takes it
 * from there. A save without a matching companion (made before, or brought in from elsewhere)
 * has no map start; the row then stays "Give up" until the next map begins.
 */
#include "genesis_runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern uint8_t g_ram[0x010000];
extern uint8_t g_rom[0x400000];

#define RESTART_POINTER   0x101FFCu    /* row label; the dialog title follows it */
#define ROW_TEXT_SITE     0x01184Cu    /* Text.l of the third record of table $011836 */
#define ROW_TEXT_ORIG     0x000EF463u  /* "Give up" */
#define SLOT_BASE         0x200003u
#define SLOT_STEP         0x5500u
#define SLOT_SUMS         0x5480u      /* six big-endian sums on the odd bytes */
#define MAPSTART_FILE     "ad-mapstart.bin"
#define MAPSTART_MAGIC    "ADMAPST1"

static const struct { uint16_t addr, size; } s_blocks[6] = {
    { 0xCC00, 0x100 }, { 0xA000, 0x1000 }, { 0xB000, 0x1800 },
    { 0xC800, 0x200 }, { 0x4000, 0x200 },  { 0xCA00, 0x100 },
};
#define BLOCK_BYTES 0x2E00

typedef struct {
    uint8_t valid, map, pad[2];
    uint8_t key[24];                   /* slot companions: the slot's checksums */
    uint8_t data[BLOCK_BYTES];
} MapStart;

static MapStart s_cur, s_slot[3];
static int s_loaded, s_fake_mode, s_save_slot = -1, s_load_slot = -1;

static void file_path(char *out, size_t size)
{
    const char *dir = getenv("GENESIS_USER_DIR");
    if (dir && *dir) snprintf(out, size, "%s/%s", dir, MAPSTART_FILE);
    else             snprintf(out, size, "%s", MAPSTART_FILE);
}

static void file_read(void)
{
    char path[1024];
    if (s_loaded) return;
    s_loaded = 1;
    file_path(path, sizeof path);
    FILE *f = fopen(path, "rb");
    if (!f) return;
    char magic[8];
    if (fread(magic, 1, 8, f) != 8 || memcmp(magic, MAPSTART_MAGIC, 8) ||
        fread(s_slot, sizeof s_slot[0], 3, f) != 3)
        memset(s_slot, 0, sizeof s_slot);
    fclose(f);
}

static void file_write(void)
{
    char path[1024];
    file_path(path, sizeof path);
    FILE *f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "[ADS] Restart: cannot write %s\n", path); return; }
    fwrite(MAPSTART_MAGIC, 1, 8, f);
    fwrite(s_slot, sizeof s_slot[0], 3, f);
    fclose(f);
}

static uint32_t label(void)
{
    static uint32_t p = 1;
    if (p == 1) {
        p = (uint32_t)g_rom[RESTART_POINTER] << 24 | (uint32_t)g_rom[RESTART_POINTER + 1] << 16 |
            (uint32_t)g_rom[RESTART_POINTER + 2] << 8 | g_rom[RESTART_POINTER + 3];
        if (p < 0x102000u || p >= 0x200000u) p = 0;      /* jp/en: no strings, no row */
    }
    return p;
}

static uint32_t title(void) { return label() + 1u + 4u * ((uint32_t)g_rom[label()] + 1u); }

static int campaign(void) { return g_ram[0xCC38] == 0; }

static int available(void)
{
    return label() && campaign() && s_cur.valid && s_cur.map == g_ram[0xCC37];
}

static int slot_of(uint32_t a0)
{
    uint32_t off = (a0 & 0xFFFFFFu) - SLOT_BASE;
    return (a0 & 0xFFFFFFu) >= SLOT_BASE && off % SLOT_STEP == 0 && off / SLOT_STEP < 3 ? (int)(off / SLOT_STEP) : -1;
}

static void slot_key(int slot, uint8_t key[24])
{
    for (uint32_t i = 0; i < 24; i++)
        key[i] = m68k_read8(SLOT_BASE + (uint32_t)slot * SLOT_STEP + SLOT_SUMS + 2u * i);
}

static void snapshot(void)
{
    uint8_t *p = s_cur.data;
    memset(&s_cur, 0, sizeof s_cur);
    if (!campaign()) return;
    for (int i = 0; i < 6; p += s_blocks[i].size, i++) memcpy(p, &g_ram[s_blocks[i].addr], s_blocks[i].size);
    s_cur.valid = 1;
    s_cur.map = g_ram[0xCC37];
    fprintf(stderr, "[ADS] Restart: start of map %u kept\n", s_cur.map);
}

static void restore(void)
{
    const uint8_t *p = s_cur.data;
    for (int i = 0; i < 6; p += s_blocks[i].size, i++) memcpy(&g_ram[s_blocks[i].addr], p, s_blocks[i].size);
    g_ram[0xCDAA] = g_ram[0xCDAB] = 0;     /* weather shown, derived by $008EBA: the loader clears it */
    fprintf(stderr, "[ADS] Restart: map %u from its start\n", s_cur.map);
}

/* Called for the hook sites below (ad_spec.c). 0 = go on, 2 = stack reset into $0085D4. */
int ad_restart_hook(uint32_t pc)
{
    switch (pc) {
    case 0x0085D4u:                    /* a map starts */
        snapshot();
        return 0;
    case 0x0117AAu: {                  /* Record menu: the third row's text */
        uint32_t text = available() ? label() : ROW_TEXT_ORIG;
        g_rom[ROW_TEXT_SITE] = (uint8_t)(text >> 24); g_rom[ROW_TEXT_SITE + 1] = (uint8_t)(text >> 16);
        g_rom[ROW_TEXT_SITE + 2] = (uint8_t)(text >> 8); g_rom[ROW_TEXT_SITE + 3] = (uint8_t)text;
        return 0;
    }
    case 0x011860u:                    /* the row's handler: tst.b $CC38 / bne → dialog */
        if (available()) { g_ram[0xCC38] = 1; s_fake_mode = 1; }
        return 0;
    case 0x01186Cu:                    /* lea $0EF45F,a1 (dialog title) */
        if (s_fake_mode) { g_ram[0xCC38] = 0; s_fake_mode = 0; }
        return 0;
    case 0x011876u:                    /* bsr $F78E, a1 = title */
        if (available()) g_cpu.A[1] = title();
        return 0;
    case 0x01189Eu:                    /* Exec.: give up in standard mode */
        if (!available()) return 0;
        restore();
        g_cpu.A[7] = (uint32_t)g_ram[0xCDA6] << 24 | (uint32_t)g_ram[0xCDA7] << 16 |
                     (uint32_t)g_ram[0xCDA8] << 8 | g_ram[0xCDA9];
        return 2;
    case 0x011AE6u:                    /* Save: a0 = slot */
        s_save_slot = slot_of(g_cpu.A[0]);
        return 0;
    case 0x011BB0u:                    /* Save done: the slot's companion */
        if (s_save_slot >= 0 && label()) {
            file_read();
            s_slot[s_save_slot] = s_cur;
            if (s_cur.valid && s_cur.map != g_ram[0xCC37]) s_slot[s_save_slot].valid = 0;
            slot_key(s_save_slot, s_slot[s_save_slot].key);
            file_write();
        }
        s_save_slot = -1;
        return 0;
    case 0x0119AAu:                    /* Load / CONTINUE: a0 = slot */
        s_load_slot = slot_of(g_cpu.A[0]);
        return 0;
    case 0x011A92u: {                  /* loaded, sums right */
        uint8_t key[24];
        memset(&s_cur, 0, sizeof s_cur);
        if (s_load_slot < 0 || !label()) return 0;
        file_read();
        slot_key(s_load_slot, key);
        if (s_slot[s_load_slot].valid && !memcmp(key, s_slot[s_load_slot].key, 24) &&
            s_slot[s_load_slot].map == g_ram[0xCC37])
            s_cur = s_slot[s_load_slot];
        fprintf(stderr, "[ADS] Restart: save %d %s\n", s_load_slot + 1,
                s_cur.valid ? "has its map start" : "has no map start");
        s_load_slot = -1;
        return 0;
    }
    default:
        return 0;
    }
}
