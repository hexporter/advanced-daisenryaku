/*
 * ad_spec.c – GameSpec for Advanced Daisenryaku (Sega, 1991), Japan Rev A.
 *
 * Minimal bring-up after the template RocketKnightAdventuresRecomp/game/rka_spec.c:
 * entry point, interrupts and ROM identity, plus game hooks. Values documented in docs/notes/roms.md.
 *   Entry  $000224   V-int $00518C   H-int $FFFF06 (RAM trampoline, resolved at runtime)
 * The dispatchers go through recomp_call_addr(): generated dispatch table,
 * on a miss the tier-3 interpreter.
 */
#include "game_spec.h"
#include "genesis_host_mem.h"
#include "genesis_runtime.h"

#include <SDL2/SDL.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern uint8_t g_ram[0x010000];
extern uint8_t g_rom[0x400000];

/* ---- Soft reset out of the V-int (docs/notes/vint.md) ----
 * In V-int mode 6 the handler jumps straight into the soft reset via bne.w $382 when a joypad
 * bit (probably START) is set, and never returns from the interrupt.
 * Irrelevant on real hardware, but the runner would stay in the V-int context for good
 * (no more yield → watchdog). Hence two steps:
 *   1. Hook $002CC2: mark the reset as pending, the handler ends as if with RTS, the V-int
 *      finishes normally.
 *   2. Hook $005AC6 (WaitForVBlank, main program): longjmp back to the entry point
 *      and run $000382 there. $000382 resets SR and the stack itself. */
#define AD_SITE_VINT_RESET   0x002CC2u
#define AD_SITE_WAIT_VBLANK  0x005AC6u
#define AD_SOFT_RESET_PC     0x000382u
#define AD_ENTRY_PC          0x000224u

/* ---- Load in the Record menu: stack reset into the map loop (docs/notes/saving.md) ----
 * $0118F2 ends with movea.l $FFCDA6,a7 / jmp $00863E: the game throws its call chain away and
 * re-enters the map loop. Until 13.11.2026 Load was left to the interpreter, which followed the
 * jump and never came back – everything after the first Load ran interpreted
 * (docs/notes/recompiler-runs.md). Now Load is native and the hook at the jmp drops the native
 * call chain like the soft reset does, then runs $00863E from the entry wrapper. A7 is the
 * value the game just loaded. */
#define AD_SITE_LOAD_JMP     0x011940u
#define AD_MAP_LOOP_PC       0x00863Eu
/* The same pattern with the main menu as target (jmp $005EAA after movea.l $FFCDA6,a7):
 * "Give up" in the Record menu ($0118E8; a play session ran interpreted from
 * Give up to the next Load) and the map loader's exit when no army is left ($00684C). */
#define AD_SITE_GIVEUP_JMP   0x0118ECu
#define AD_SITE_NOARMY_JMP   0x006850u
#define AD_MAIN_MENU_PC      0x005EAAu
/* "Restart" (ad_restart.c): the map's start is put back and the map entry $0085D4 runs again. */
#define AD_MAP_START_PC      0x0085D4u

static jmp_buf s_soft_reset_jmp;
static void   *s_entry_tail_frame;
static int     s_soft_reset_armed;
static int     s_soft_reset_pending;
static uint32_t s_restart_pc;         /* target of a stack-reset jump (longjmp value 2) */

static void ad_call_entry_point(void)
{
    volatile uint32_t pc = AD_ENTRY_PC;
    /* The tr ROM is larger than 2 MiB and overlaps the battery RAM at $200000-$20FFFF; such a
     * cartridge shows its RAM only while bit 0 of $A130F1 is set. The game (1 MiB) never writes
     * that register, so the port sets it before the game starts. */
    if (AD_ROM_SIZE > 0x200000u) m68k_write8(0xA130F1u, 1);
    s_entry_tail_frame = recomp_tail_frame_get();
    int why = setjmp(s_soft_reset_jmp);
    if (why) {
        /* Discard the guest's abandoned call chain, like the hardware does on a stack reset. */
        recomp_tail_frame_set(s_entry_tail_frame);
        g_split_sp_popped = 0;
        g_rte_pending = 0;
        if (why == 2) {
            pc = s_restart_pc;               /* A7 set by the game */
            if (pc == AD_MAP_LOOP_PC)
                fprintf(stderr, "[ADS] Load: map loop restarted at $%06X, A7 $%06X\n",
                        (unsigned)pc, (unsigned)(g_cpu.A[7] & 0xFFFFFFu));
            else
                fprintf(stderr, "[ADS] Stack reset: restarted at $%06X, A7 $%06X\n",
                        (unsigned)pc, (unsigned)(g_cpu.A[7] & 0xFFFFFFu));
        } else {
            g_cpu.A[7] = 0xFFFFFF00u;
            pc = AD_SOFT_RESET_PC;
            fprintf(stderr, "[ADS] Soft reset out of V-int: restart at $%06X\n", (unsigned)pc);
        }
    }
    s_soft_reset_armed = 1;
    recomp_call_addr(pc);
}

/* ---- RAM recording with phase marking (docs/notes/phases.md) ----
 * Only active with the environment variable AD_RAMLOG=<file> (tools/run.sh --ramlog).
 * Hook $0051A2 in the V-int (every frame, even while the main program computes for a long time):
 * one record every AD_RAMLOG_EVERY frames (default 8) and on every phase change.
 * Phase via key in the game window: 0 other, 1 own turn, 2 enemy turn, 3 battle.
 * Format (analysis: tools/ramphase.py): header "ADRAMLG1", then per record
 *   u32 V-int counter, u8 phase, u8 kind (0 = full 64 KiB, 1 = changes), u16 0, u32 n,
 *   kind 0: 65536 bytes of RAM, kind 1: n × (u16 address, u8 value); all big-endian. */
#define AD_SITE_VINT_FRAME   0x0051A2u

static FILE    *s_ramlog;
static int      s_ramlog_init;
static uint32_t s_ramlog_every = 8;
static uint32_t s_ramlog_vints;
static uint8_t  s_ramlog_phase;
static uint8_t  s_ramlog_prev[0x10000];
static uint8_t  s_ramlog_delta[0x10000 * 3];

static const char *const s_phase_names[] = { "other", "own turn", "enemy turn", "battle" };

static void ramlog_put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;
}

static void ramlog_write(int full)
{
    uint32_t n = 0;
    if (!full) {
        for (uint32_t a = 0; a < 0x10000u; a++) {
            if (g_ram[a] == s_ramlog_prev[a]) continue;
            s_ramlog_delta[n * 3]     = (uint8_t)(a >> 8);
            s_ramlog_delta[n * 3 + 1] = (uint8_t)a;
            s_ramlog_delta[n * 3 + 2] = g_ram[a];
            n++;
        }
        if (n > 0x10000u / 3) full = 1;   /* a full record is smaller then */
    }
    uint8_t hdr[12];
    ramlog_put32(hdr, s_ramlog_vints);
    hdr[4] = s_ramlog_phase;
    hdr[5] = full ? 0 : 1;
    hdr[6] = hdr[7] = 0;
    ramlog_put32(hdr + 8, full ? 0x10000u : n);
    fwrite(hdr, 1, sizeof hdr, s_ramlog);
    if (full) fwrite(g_ram, 1, 0x10000u, s_ramlog);
    else      fwrite(s_ramlog_delta, 3, n, s_ramlog);
    memcpy(s_ramlog_prev, g_ram, sizeof s_ramlog_prev);
}

static void ramlog_vint(void)
{
    if (!s_ramlog_init) {
        s_ramlog_init = 1;
        const char *path = getenv("AD_RAMLOG");
        if (!path || !*path) return;
        const char *every = getenv("AD_RAMLOG_EVERY");
        if (every && atoi(every) > 0) s_ramlog_every = (uint32_t)atoi(every);
        s_ramlog = fopen(path, "wb");
        if (!s_ramlog) { fprintf(stderr, "[ADS] RAM recording: cannot write %s\n", path); return; }
        fwrite("ADRAMLG1", 1, 8, s_ramlog);
        fprintf(stderr, "[ADS] RAM recording to %s, every %u frames; phase via key "
                        "0 other, 1 own turn, 2 enemy turn, 3 battle on/off\n",
                path, (unsigned)s_ramlog_every);
        ramlog_write(1);
        return;
    }
    if (!s_ramlog) return;
    s_ramlog_vints++;

    /* 0–2 set the phase; 3 toggles: a battle starts or ends (back to the previous phase). */
    const Uint8 *ks = SDL_GetKeyboardState(NULL);
    static const SDL_Scancode keys[4] = { SDL_SCANCODE_0, SDL_SCANCODE_1, SDL_SCANCODE_2, SDL_SCANCODE_3 };
    static uint8_t key3_down, phase_before_battle;
    int toggle = ks && ks[SDL_SCANCODE_3] && !key3_down;
    key3_down = ks && ks[SDL_SCANCODE_3];
    for (uint8_t p = 0; p < 4; p++) {
        uint8_t next = p;
        if (p == 3) {
            if (!toggle) continue;
            if (s_ramlog_phase == 3) next = phase_before_battle;
            else phase_before_battle = s_ramlog_phase;
        } else if (!ks || !ks[keys[p]] || p == s_ramlog_phase) {
            continue;
        }
        s_ramlog_phase = next;
        fprintf(stderr, "[ADS] Phase %u (%s) from V-int %u\n", next, s_phase_names[next], (unsigned)s_ramlog_vints);
        ramlog_write(0);
        fflush(s_ramlog);
        return;
    }
    if (s_ramlog_vints % s_ramlog_every == 0) ramlog_write(0);
    if (s_ramlog_vints % 600u == 0) fflush(s_ramlog);
}

/* ---- Automatic fast-forward during enemy turns (docs/notes/phases.md) ----
 * Computer's turn ($FFCDD2 = 1) and no battle animation (V-int mode $FF0110 = 4 and
 * $FFCD04 = $46/$66) → request fast-forward (framework patch 0005). Evidence: 3 recordings
 * (2 maps with one enemy, Ural with 3–4 enemies), 7 enemy turns, 28 battles. The mode
 * leaves 4 at the end of the animation, $FFCD04 only ~0.9 s later (black screen) – so the
 * black screen is fast-forwarded too. Switch on only once the state has
 * held for 8 V-ints – a brief flicker during a battle would otherwise skip up to 128 frames of
 * animation; switch off immediately.
 * AD_AUTO_FF=<factor> (default 128, capped by GENESIS_FF_MAX), 0 = off for this launch.
 *
 * Two rows of the System settings screen (below) switch it: "Fast enemy turn" ON/OFF and
 * "Enemy battles" 1x / 2x / 4x / MAX – the speed of the battle animations during the
 * computer's turn (MAX = the factor above). Kept in ad-port.ini (fast_enemy_turn = on|off,
 * enemy_battles = 1x|2x|4x|max). A lower speed takes effect at once, a higher one only after
 * it has been asked for 8 V-ints in a row: the battle state leaves its values for single frames
 * (docs/notes/frame.md), which must not skip animation. */
#define AD_RAM_CPU_TURN      0xCDD2u   /* $FFCDD2, 1 = computer's turn */
#define AD_RAM_SCREEN        0xCD04u   /* $FFCD04, $46/$66 = battle (including the black screen after it) */
#define AD_RAM_VINT_MODE     0x0110u   /* $FF0110, 4 = battle animation (vint.md) */
#define AD_AUTO_FF_SETTLE    8u
/* System menu (Record, Sound, ...): A/B/C during the computer's turn opens it ($00C6CE, jsr
 * $0100CA, back at $00C6FA). No fast-forward while it is open: at 128x the menu is unusable
 * and its handlers (run by the interpreter floor) hit the instruction guard (Record
 * stopped working; docs/notes/saving.md). */
#define AD_SITE_SYSMENU_OPEN  0x0100CAu
/* Sound commands (docs/notes/sound.md, "Lost commands"). The 68K writes each command to the one
 * slot $A01C0A; a second write before the Z80 has read it replaces the first, and the driver
 * takes a command only when its priority beats the sound playing ($1C18). The title menu's stop
 * $E1 (priority 3) must win over both: before it the priority is cleared, and an effect
 * ($90-$DF) never replaces an unread stop or music command (it is dropped instead).
 * $00857E: move.b d0,$A01C0A (bus held); $008584: bus released. AD_SND_LOG=1 logs every command. */
#define AD_SITE_SOUND_CMD     0x00857Eu
#define AD_SITE_SOUND_DONE    0x008584u
#define SND_IS_EFFECT(c)      ((c) >= 0x90u && (c) < 0xE0u)
static uint32_t s_snd_d0;
static int s_snd_restore;
#define AD_SITE_SYSMENU_DONE  0x00C6FAu

static int s_sysmenu_open;

static double s_auto_ff = -1.0;
static int s_ff_on = 1;                 /* "Fast enemy turn" */
static int s_ff_battle;                 /* "Enemy battles": 0 1x, 1 2x, 2 4x, 3 MAX */
static const char *const s_ff_battle_name[4] = { "1x", "2x", "4x", "max" };

const char *ad_port_setting(const char *key);           /* ad_lang.c */
void ad_port_store(const char *key, const char *value);

static void auto_ff_init(void)
{
    if (s_auto_ff >= 0.0) return;
    const char *e = getenv("AD_AUTO_FF"), *v;
    s_auto_ff = e ? atof(e) : 128.0;
    if (s_auto_ff <= 1.0) { s_auto_ff = 128.0; s_ff_on = 0; }
    else if ((v = ad_port_setting("fast_enemy_turn"))) s_ff_on = strcmp(v, "off") != 0;
    if ((v = ad_port_setting("enemy_battles")))
        for (int i = 0; i < 4; i++) if (!strcmp(v, s_ff_battle_name[i])) s_ff_battle = i;
    fprintf(stderr, "[ADS] Automatic fast-forward during enemy turns: %s, battles %s\n",
            s_ff_on ? "on" : e && atof(e) <= 1.0 ? "off (AD_AUTO_FF)" : "off", s_ff_battle_name[s_ff_battle]);
}

static double ff_battle_factor(void)
{
    static const double f[3] = { 0.0, 2.0, 4.0 };
    return s_ff_battle < 3 ? f[s_ff_battle] : s_auto_ff;
}

static void auto_ff_vint(void)
{
    static uint32_t settled;
    static double pending;
    auto_ff_init();
    uint8_t screen = g_ram[AD_RAM_SCREEN];
    int battle = (screen == 0x46u || screen == 0x66u) && g_ram[AD_RAM_VINT_MODE] == 4u;
    if (g_ram[AD_RAM_CPU_TURN] != 1u)
        s_sysmenu_open = 0;             /* left without passing $00C6FA (e.g. Load) */
    double target = 0.0;
    if (s_ff_on && g_ram[AD_RAM_CPU_TURN] == 1u && !s_sysmenu_open)
        target = battle ? ff_battle_factor() : s_auto_ff;
    if (target != pending) { pending = target; settled = 0; }
    double before = g_game_ff_request;
    if (target <= g_game_ff_request) g_game_ff_request = target;
    else if (++settled >= AD_AUTO_FF_SETTLE) g_game_ff_request = target;
    static int log = -1;
    if (log < 0) log = getenv("AD_FF_LOG") && atoi(getenv("AD_FF_LOG")) > 0;
    if (log && g_game_ff_request != before)
        fprintf(stderr, "[ADS] Auto FF %gx (%s)\n", g_game_ff_request, battle ? "battle" : "turn");
}

void ad_mapzoom_vint(void);   /* ad_mapzoom.c */
void ad_record_vint(void);    /* ad_record.c */
void ad_frame_vint(void);     /* ad_frame.c */
int  ad_restart_hook(uint32_t pc);           /* ad_restart.c */
int  ad_mapzoom_frame_step(int in_scroll);   /* ad_mapzoom.c */

/* The four view scroll routines ($915E/$91FA/$9298/$9348) are only called from these two blocks;
 * each step ends in the frame step $01405A (docs/notes/map.md). */
#define AD_SITE_SCROLL_A      0x008856u
#define AD_SITE_SCROLL_A_END  0x008866u
#define AD_SITE_SCROLL_B      0x0090BEu
#define AD_SITE_SCROLL_B_END  0x0090CEu
#define AD_SITE_FRAME_STEP    0x01405Au
static int s_in_view_scroll;

/* "HD map ON/OFF" as a fifth row of the System settings screen $012476 (System menu → System;
 * docs/notes/menu.md). The screen is a table of 14-byte records (ID.w = plane row offset,
 * Text.l, Draw.l, Action.l; $FFFF ends it) that $0124E8 copies from $01250A to $FFE420. No
 * 68000 code is added: the new record reuses the handlers of row 4 ("Pick counter weapon",
 * flag $FFCC1E), and hooks swap that flag for the zoom state while they run for our row.
 * The label is a string the translation build adds (tools/translate_rom.py, pointer at
 * $101FF0); without it (jp/en) the screen stays as it is.
 *
 * "Language" is a sixth row in the same way (ad_lang.c; label and value strings from the
 * language block of the translation build). Its value is not ON/OFF: at the draw handler's
 * jmp the hook puts the value string ("English" / "Japanese") into a0. Six rows do not
 * fit below the title, so the whole screen sits three tile rows higher: the hooks after the
 * two lea move a1 (boxes, title) and the list's first row ($FFCD35) is 8 instead of 11. */
#define AD_SITE_SET_BOXES    0x0124A4u   /* after lea $FF828A,a1: both boxes are copied there */
#define AD_SITE_SET_TITLE    0x0124C4u   /* jsr $8166: the title, a1 = its place */
#define AD_SET_SHIFT         3
#define AD_SITE_SET_BOX      0x0124DCu   /* jsr $7D5E: box copied, title drawn */
#define AD_SITE_SET_TABLE    0x0124FCu   /* jsr $7D64: table copied to $FFE420 */
#define AD_SITE_SET_DRAW     0x01259Eu   /* draw handler of row 4, a0 = the record's text */
#define AD_SITE_SET_DRAW_TST 0x0125AAu   /* tst.b $CC1E */
#define AD_SITE_SET_DRAW_END 0x0125B6u   /* jmp $8166 (value string) */
#define AD_SITE_SET_ACTION   0x0125E4u   /* eori.b #1,$CC1E; a1 = the record's text */
#define AD_SET_LABEL_PTR     0x101FF0u
/* "Fast enemy turn" and "Enemy battles" (automatic fast-forward, above) as the second and
 * third row: six long pointers at $101FEC's target – the two labels, the four values of the
 * second. Eight rows need the whole screen: the title box moves to rows 0–3 and the list's box
 * starts on the title box's bottom border (row 3), first row at 4, bottom border at row 27. */
#define AD_SET_SPEED_PTR     0x101FECu
#define AD_SET_FIRST_ROW     4
#define AD_RAM_SET_TABLE     0xE420u
#define AD_RAM_SET_FLAG4     0xCC1Eu
#define AD_RAM_PLANE_A       0x8000u     /* plane A shadow, 128 bytes per row */

int  ad_mapzoom_enabled(void);        /* ad_mapzoom.c */
void ad_mapzoom_toggle(void);
int  ad_lang_available(void);         /* ad_lang.c */
void ad_lang_toggle(void);
uint32_t ad_lang_label(void);
uint32_t ad_lang_value(void);
void ad_lang_vint(void);

static uint32_t set_speed(int i)           /* 0, 1 labels; 2–5 values */
{
    static uint32_t p[6] = { 1 };
    if (p[0] == 1) {
        memset(p, 0, sizeof p);
        uint32_t t = (uint32_t)g_rom[AD_SET_SPEED_PTR] << 24 | (uint32_t)g_rom[AD_SET_SPEED_PTR + 1] << 16 |
                     (uint32_t)g_rom[AD_SET_SPEED_PTR + 2] << 8 | g_rom[AD_SET_SPEED_PTR + 3];
        if (AD_ROM_SIZE >= 0x200000u && t >= 0x102000u && t < 0x200000u - 24u)
            for (int k = 0; k < 6; k++) {
                uint32_t a = t + 4u * (uint32_t)k;
                p[k] = (uint32_t)g_rom[a] << 24 | (uint32_t)g_rom[a + 1] << 16 | (uint32_t)g_rom[a + 2] << 8 | g_rom[a + 3];
                if (p[k] < 0x102000u || p[k] >= 0x200000u) { memset(p, 0, sizeof p); break; }
            }
    }
    return p[i];
}

static uint32_t set_label(void)
{
    static uint32_t label = 1;
    if (label == 1) {
        label = 0;
        if (AD_ROM_SIZE >= 0x200000u) {
            uint32_t p = (uint32_t)g_rom[AD_SET_LABEL_PTR] << 24 | (uint32_t)g_rom[AD_SET_LABEL_PTR + 1] << 16 |
                         (uint32_t)g_rom[AD_SET_LABEL_PTR + 2] << 8 | g_rom[AD_SET_LABEL_PTR + 3];
            if (p >= 0x102000u && p < 0x200000u) label = p;
        }
    }
    return label;
}

/* The box is 30 tiles wide from column 5: rows 10 (top border) to 22 (bottom border), option
 * rows 11/14/17/20 (two tile rows each), blank rows between – all `shift` rows higher when the
 * screen is moved up. Each added row needs three more: the bottom border moves down, the rows
 * from the old border on become blank interior (a copy of the row below the first option). */
static void set_extend_box(int shift, int added)
{
    uint8_t *p = &g_ram[AD_RAM_PLANE_A];
    int border = 22 - shift, blank = 13 - shift;
    memcpy(p + (border + 3 * added) * 128 + 10, p + border * 128 + 10, 60);
    for (int r = border; r < border + 3 * added; r++) memcpy(p + r * 128 + 10, p + blank * 128 + 10, 60);
}

/* Record `row` (0-based) of the RAM table, with the handlers of row 4, and the terminator. */
static void set_append_row(int row, uint32_t label)
{
    uint8_t *r = &g_ram[AD_RAM_SET_TABLE + row * 14];
    static const uint8_t handlers[8] = { 0x00, 0x01, 0x25, 0x9E, 0x00, 0x01, 0x25, 0xE4 };
    r[0] = 0x00; r[1] = (uint8_t)(3 * row);            /* ID: tile rows below row 1 */
    r[2] = (uint8_t)(label >> 24); r[3] = (uint8_t)(label >> 16);
    r[4] = (uint8_t)(label >> 8);  r[5] = (uint8_t)label;
    memcpy(r + 6, handlers, 8);
    r[14] = r[15] = 0xFF;
}

/* Eight rows: after the boxes are copied (three rows up, see AD_SET_SHIFT) the title box goes
 * to rows 0–3 and the list's box up to row 3, where its top border replaces the title box's
 * bottom border; then the box grows by four rows. */
static void set_eight_rows(void)
{
    uint8_t *p = &g_ram[AD_RAM_PLANE_A];
    int shift = 11 - AD_SET_FIRST_ROW;
    memmove(p, p + 2 * 128, 4 * 128);                                       /* rows 2–5 → 0–3 */
    memmove(p + (AD_SET_FIRST_ROW - 1) * 128, p + (10 - AD_SET_SHIFT) * 128, 13 * 128);  /* 7–19 → 3–15 */
    set_extend_box(shift, 4);
}

/* Records of the RAM table for eight rows: Battle speed, the two fast-forward rows, the game's
 * other three, HD map, Language. */
static void set_table_eight(void)
{
    uint8_t game[3][14];
    memcpy(game, &g_ram[AD_RAM_SET_TABLE + 14], sizeof game);
    set_append_row(1, set_speed(0));
    set_append_row(2, set_speed(1));
    for (int i = 0; i < 3; i++) {
        uint8_t *r = &g_ram[AD_RAM_SET_TABLE + (3 + i) * 14];
        memcpy(r, game[i], 14);
        r[0] = 0x00; r[1] = (uint8_t)(3 * (3 + i));
    }
    set_append_row(6, set_label());
    set_append_row(7, ad_lang_label());
    g_ram[0xCD37] = 3 * 7 + 2;          /* rows are drawn while ID < $FFCD37 ($007FF6; game: $11) */
}

/* After a language switch the screen's title is drawn again the way $0124B2 does it (tile base
 * $803C, string $0EF441, drawing with the plane transfer off); the list redraws itself. */
static void set_redraw_title(void)
{
    M68KState cpu = g_cpu;
    uint8_t transfer = g_ram[0xCDA0], base[2] = { g_ram[0xCD04], g_ram[0xCD05] };
    g_ram[0xCDA0] = 0;
    g_ram[0xCD04] = 0x80; g_ram[0xCD05] = 0x3C;
    g_cpu.A[0] = 0x000EF441u;
    g_cpu.A[1] = 0x00FF8320u - (set_speed(0) ? AD_SET_SHIFT + 2 : AD_SET_SHIFT) * 128u;
    recomp_call_addr(0x008166u);
    g_cpu = cpu;
    g_ram[0xCD04] = base[0]; g_ram[0xCD05] = base[1];
    g_ram[0xCDA0] = transfer;
}

/* Campaign start date (experiment; docs/notes/campaign.md):
 * AD_CAMPAIGN_START=YY.M.D replaces the date of the campaign's first map. Only the first map
 * takes its record's date ($006488 with $FFCDC3 set: $0064A6 / $0064FC); later maps go on
 * from the current date, and the units on offer follow the date (table $0280EC). */
#define AD_SITE_DATE_A       0x0064B8u   /* after the first-map date is set (map loader) */
#define AD_SITE_DATE_B       0x00650Eu   /* the loader's other path joins here */

/* Start year in the title menu (docs/notes/campaign.md): a row "CAMPAIGN START 1939" below the
 * others; A steps through 1939 (the game's own date) … 1946 (1 January of the year; from 1946
 * every unit entry is on offer). Like the "HD map" row no 68000 code is added: a hook appends a
 * record to the RAM copy of the menu table ($FFE420; draw handler $006026, action handler
 * $005FDA of the button-layout row), and while that handler runs for our row its effects are
 * undone: $FFCDE7 is flipped beforehand and the two SRAM bytes it writes ($20FFF9/$20FFFB)
 * are put back at its two exits. The texts come from the translation build (pointer at
 * $101FF4, eight strings of one length); without them (jp/en) the menu stays as it is. */
#define AD_SITE_TITLE_TABLE  0x005F4Cu   /* bsr $7D5E: table copied to $FFE420 */
#define AD_SITE_TITLE_ACTION 0x005FDAu   /* button-layout handler, a1 = the record's text */
#define AD_SITE_TITLE_EXIT_A 0x005FF2u   /* its two bra.w $5F50 */
#define AD_SITE_TITLE_EXIT_B 0x006000u
#define AD_START_TEXT_PTR    0x101FF4u
#define AD_START_YEARS       8

static int s_start_year = -1;   /* 0 = 1939 (the game's own date), n = 1 January 1939 + n;
                                   kept in ad-port.ini as campaign_start = 1939..1946 */

static void start_year_init(void)
{
    if (s_start_year >= 0) return;
    const char *v = ad_port_setting("campaign_start");
    int y = v ? atoi(v) : 1939;
    s_start_year = y > 1939 && y < 1939 + AD_START_YEARS ? y - 1939 : 0;
}
static int s_title_undo;
static uint8_t s_title_sram[2];

static uint32_t start_texts(void)
{
    static uint32_t base = 1;
    if (base == 1) {
        base = 0;
        if (AD_ROM_SIZE >= 0x200000u) {
            uint32_t p = (uint32_t)g_rom[AD_START_TEXT_PTR] << 24 | (uint32_t)g_rom[AD_START_TEXT_PTR + 1] << 16 |
                         (uint32_t)g_rom[AD_START_TEXT_PTR + 2] << 8 | g_rom[AD_START_TEXT_PTR + 3];
            if (p >= 0x102000u && p < 0x200000u) base = p;
        }
    }
    return base;
}

/* The eight strings have one length: count - 1, then the glyph codes. */
static uint32_t start_stride(void)
{
    return start_texts() ? (uint32_t)g_rom[start_texts()] + 2u : 0u;
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;
}

/* "QUIT GAME", right after the eight year strings (8x8 menu font, at most 19 characters). */
static uint32_t quit_text(void)
{
    if (!start_texts()) return 0;
    uint32_t q = start_texts() + start_stride() * AD_START_YEARS;
    return g_rom[q] < 19u ? q : 0;
}

/* Our record in the RAM table, or the terminator's place when it is not there yet. */
static uint8_t *title_row(int *found, unsigned *last_id)
{
    uint8_t *r = &g_ram[AD_RAM_SET_TABLE];
    *found = 0; *last_id = 0;
    for (int i = 0; i < 8; i++, r += 14) {
        if (r[0] == 0xFF && r[1] == 0xFF) return r;
        uint32_t text = (uint32_t)r[3] << 16 | (uint32_t)r[4] << 8 | r[5];
        if (text >= start_texts() && text < start_texts() + start_stride() * AD_START_YEARS) { *found = 1; return r; }
        *last_id = (unsigned)r[0] << 8 | r[1];
    }
    return NULL;
}

/* Insert a record at row `at` of the RAM table; later records (and the terminator) move one
 * row down and their IDs by 2. */
static void title_insert(int at, unsigned id, uint32_t text)
{
    uint8_t *r = &g_ram[AD_RAM_SET_TABLE + at * 14], *end = &g_ram[AD_RAM_SET_TABLE];
    int n = 0;
    while ((end[0] != 0xFF || end[1] != 0xFF) && n < 8) { end += 14; n++; }   /* the terminator */
    if (n >= 8 || end < r) return;
    memmove(r + 14, r, (size_t)(end - r) + 2);
    for (uint8_t *q = r + 14; q < end + 14; q += 14) {
        unsigned n = ((unsigned)q[0] << 8 | q[1]) + 2u;
        q[0] = (uint8_t)(n >> 8); q[1] = (uint8_t)n;
    }
    r[0] = (uint8_t)(id >> 8); r[1] = (uint8_t)id;
    put32(r + 2, text);
    put32(r + 6, 0x006026u);
    put32(r + 10, AD_SITE_TITLE_ACTION);
}

/* Our rows go in as the fifth (start year) and sixth (QUIT GAME): $FFCD30 (3) is the last row
 * the cursor reaches, and the longer table $005F92 keeps an entry beyond it (the program at
 * $0FA000) that must stay out of reach. */
static void title_append_row(void)
{
    int found; unsigned last;
    if (!title_row(&found, &last) || found) return;
    start_year_init();
    title_insert(4, 0x08, start_texts() + start_stride() * (unsigned)s_start_year);
    unsigned rows = 4;
    if (quit_text()) { title_insert(5, 0x0A, quit_text()); rows = 5; }
    g_ram[0xCD30] = 0x00; g_ram[0xCD31] = (uint8_t)rows;    /* last row: 3 -> 4 or 5 */
}

static void campaign_start_date(void)
{
    static int y = -1, m, d;
    if (y < 0) {
        const char *e = getenv("AD_CAMPAIGN_START");
        y = 0;
        static const int days[12] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
        if (e && sscanf(e, "%d.%d.%d", &y, &m, &d) == 3 &&
            y >= 39 && y <= 99 && m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1])
            fprintf(stderr, "[ADS] Campaign start date: %d.%d.%d (AD_CAMPAIGN_START)\n", y, m, d);
        else {
            if (e) fprintf(stderr, "[ADS] AD_CAMPAIGN_START: expected YY.M.D (year 39-99)\n");
            y = 0;
        }
    }
    /* campaign ($FFCC38 = 0), first map ($FFCDC3 set) */
    if (g_ram[0xCC38] != 0 || g_ram[0xCDC3] == 0) return;
    int sy = y, sm = m, sd = d;
    start_year_init();
    if (s_start_year) { sy = 39 + s_start_year; sm = 1; sd = 1; }    /* the title menu's choice */
    if (!sy) return;
    g_ram[0xCC14] = (uint8_t)sy; g_ram[0xCC15] = (uint8_t)sm; g_ram[0xCC16] = (uint8_t)sd;
    fprintf(stderr, "[ADS] Campaign: first map starts on %d.%d.%d\n", sy, sm, sd);
}

static int s_set_draw;          /* the draw handler runs for our row: 1 HD map, 2 Language, 3 Fast enemy turn, 4 Enemy battles */
static uint8_t s_set_saved;

static int ad_instruction_hook(uint32_t pc)
{
    switch (pc) {
    case AD_SITE_TITLE_TABLE:
        if (start_texts()) title_append_row();
        return 0;
    case AD_SITE_TITLE_ACTION:
        if (start_texts() && (g_cpu.A[1] & 0xFFFFFFu) >= start_texts() &&
            (g_cpu.A[1] & 0xFFFFFFu) < start_texts() + start_stride() * AD_START_YEARS) {
            int found; unsigned last;
            uint8_t *r = title_row(&found, &last);
            s_start_year = (s_start_year + 1) % AD_START_YEARS;
            if (r && found) put32(r + 2, start_texts() + start_stride() * (unsigned)s_start_year);
            fprintf(stderr, "[ADS] Campaign start year: %d\n", 1939 + s_start_year);
            char buf[8];
            snprintf(buf, sizeof buf, "%d", 1939 + s_start_year);
            ad_port_store("campaign_start", buf);
            g_ram[0xCDE7] ^= 1u;                    /* the eori that follows undoes this */
            s_title_sram[0] = m68k_read8(0x20FFF9u);
            s_title_sram[1] = m68k_read8(0x20FFFBu);
            s_title_undo = 1;
        } else if (quit_text() && (g_cpu.A[1] & 0xFFFFFFu) == quit_text()) {
            /* QUIT GAME: the runner's own quit, as when the window is closed (SRAM is written) */
            fprintf(stderr, "[ADS] Title menu: quit\n");
            SDL_Event ev = { .type = SDL_QUIT };
            SDL_PushEvent(&ev);
            g_ram[0xCDE7] ^= 1u;
            s_title_sram[0] = m68k_read8(0x20FFF9u);
            s_title_sram[1] = m68k_read8(0x20FFFBu);
            s_title_undo = 1;
        }
        return 0;
    case AD_SITE_TITLE_EXIT_A:
    case AD_SITE_TITLE_EXIT_B:
        if (s_title_undo) {
            m68k_write8(0x20FFF9u, s_title_sram[0]);
            m68k_write8(0x20FFFBu, s_title_sram[1]);
            s_title_undo = 0;
        }
        return 0;
    case AD_SITE_DATE_A:
    case AD_SITE_DATE_B:
        campaign_start_date();
        return 0;
    case AD_SITE_SET_BOXES:
    case AD_SITE_SET_TITLE:
        if (set_label() && ad_lang_available()) g_cpu.A[1] -= AD_SET_SHIFT * 128u;
        return 0;
    case AD_SITE_SET_BOX:
        if (set_label() && ad_lang_available() && set_speed(0)) {
            g_ram[0xCD30] = 0x00; g_ram[0xCD31] = 0x07;                 /* last row: 3 -> 7 */
            g_ram[0xCD35] = AD_SET_FIRST_ROW;                           /* the list's first row */
            set_eight_rows();
        } else if (set_label()) {
            int lang = ad_lang_available();
            g_ram[0xCD30] = 0x00; g_ram[0xCD31] = lang ? 0x05 : 0x04;   /* last row: 3 -> 4 or 5 */
            if (lang) g_ram[0xCD35] = (uint8_t)(11 - AD_SET_SHIFT);     /* the list's first row */
            set_extend_box(lang ? AD_SET_SHIFT : 0, lang ? 2 : 1);
        }
        return 0;
    case AD_SITE_SET_TABLE:
        if (set_label() && ad_lang_available() && set_speed(0)) set_table_eight();
        else if (set_label()) {
            set_append_row(4, set_label());
            if (ad_lang_available()) set_append_row(5, ad_lang_label());
        }
        return 0;
    case AD_SITE_SET_DRAW: {
        uint32_t text = g_cpu.A[0] & 0xFFFFFFu;
        s_set_draw = set_label() && text == set_label() ? 1
                   : ad_lang_available() && text == ad_lang_label() ? 2
                   : set_speed(0) && text == set_speed(0) ? 3
                   : set_speed(1) && text == set_speed(1) ? 4 : 0;
        return 0;
    }
    case AD_SITE_SET_DRAW_TST:
        if (s_set_draw == 1 || s_set_draw == 3) {
            auto_ff_init();
            s_set_saved = g_ram[AD_RAM_SET_FLAG4];
            g_ram[AD_RAM_SET_FLAG4] = (uint8_t)(s_set_draw == 1 ? ad_mapzoom_enabled() : s_ff_on);
        }
        return 0;
    case AD_SITE_SET_DRAW_END:
        if (s_set_draw == 1 || s_set_draw == 3) g_ram[AD_RAM_SET_FLAG4] = s_set_saved;
        if (s_set_draw == 2) g_cpu.A[0] = ad_lang_value();
        if (s_set_draw == 4) { auto_ff_init(); g_cpu.A[0] = set_speed(2 + s_ff_battle); }
        s_set_draw = 0;
        return 0;
    case AD_SITE_SET_ACTION:
        if (set_label() && (g_cpu.A[1] & 0xFFFFFFu) == set_label()) {
            ad_mapzoom_toggle();
            g_ram[AD_RAM_SET_FLAG4] ^= 1u;      /* the eori that follows undoes this */
        } else if (ad_lang_available() && (g_cpu.A[1] & 0xFFFFFFu) == ad_lang_label()) {
            ad_lang_toggle();
            set_redraw_title();
            g_ram[AD_RAM_SET_FLAG4] ^= 1u;
        } else if (set_speed(0) && (g_cpu.A[1] & 0xFFFFFFu) == set_speed(0)) {
            auto_ff_init();
            s_ff_on = !s_ff_on;
            ad_port_store("fast_enemy_turn", s_ff_on ? "on" : "off");
            fprintf(stderr, "[ADS] Fast enemy turn: %s\n", s_ff_on ? "on" : "off");
            g_ram[AD_RAM_SET_FLAG4] ^= 1u;
        } else if (set_speed(1) && (g_cpu.A[1] & 0xFFFFFFu) == set_speed(1)) {
            auto_ff_init();
            s_ff_battle = (s_ff_battle + 1) % 4;
            ad_port_store("enemy_battles", s_ff_battle_name[s_ff_battle]);
            fprintf(stderr, "[ADS] Enemy battles: %s\n", s_ff_battle_name[s_ff_battle]);
            g_ram[AD_RAM_SET_FLAG4] ^= 1u;
        }
        return 0;
    case AD_SITE_VINT_FRAME:
        ad_lang_vint();
        ramlog_vint();
        auto_ff_vint();
        ad_mapzoom_vint();
        ad_record_vint();
        ad_frame_vint();
        return 0;
    case AD_SITE_SCROLL_A:
    case AD_SITE_SCROLL_B:
        s_in_view_scroll = 1;
        return 0;
    case AD_SITE_SCROLL_A_END:
    case AD_SITE_SCROLL_B_END:
        s_in_view_scroll = 0;
        return 0;
    case AD_SITE_FRAME_STEP:
        return ad_mapzoom_frame_step(s_in_view_scroll);       /* 1 = implicit RTS */
    case AD_SITE_SOUND_CMD: {
        /* Bus held: $A01C0A still holds a command the Z80 has not read, if any. */
        uint8_t cmd = (uint8_t)g_cpu.D[0], pending = glue_peek8(0xA01C0Au);
        static int log = -1;
        if (log < 0) log = getenv("AD_SND_LOG") && atoi(getenv("AD_SND_LOG")) > 0;
        if (log) {
            uint32_t sp = g_cpu.A[7] & 0xFFFFu;
            uint32_t ret = (uint32_t)g_ram[sp + 1] << 16 | (uint32_t)g_ram[sp + 2] << 8 | g_ram[sp + 3];
            fprintf(stderr, "[ADS] Sound $%02X from $%06X (driver: pending $%02X, priority $%02X)\n",
                    cmd, (unsigned)ret - 4u, pending, glue_peek8(0xA01C18u));
        }
        if (cmd == 0xE1u) {                     /* rare (title menu): always in run.log */
            uint8_t prio = glue_peek8(0xA01C18u);
            if (!log) fprintf(stderr, "[ADS] Sound stop $E1 (driver: pending $%02X, priority $%02X)\n", pending, prio);
            glue_poke8(0xA01C18u, 0);           /* the stop must not lose to a click still playing */
        } else if (SND_IS_EFFECT(cmd) && pending && !SND_IS_EFFECT(pending)) {
            fprintf(stderr, "[ADS] Sound $%02X dropped: $%02X not read yet\n", cmd, pending);
            s_snd_d0 = g_cpu.D[0];               /* keep the stop/music in the slot, drop the click */
            g_cpu.D[0] = (g_cpu.D[0] & ~0xFFu) | pending;
            s_snd_restore = 1;
        }
        return 0;
    }
    case AD_SITE_SOUND_DONE:
        if (s_snd_restore) { g_cpu.D[0] = s_snd_d0; s_snd_restore = 0; }
        return 0;
    case AD_SITE_SYSMENU_OPEN:
        s_sysmenu_open = 1;
        g_game_ff_request = 0.0;
        return 0;
    case AD_SITE_SYSMENU_DONE:
        s_sysmenu_open = 0;
        return 0;
    case AD_SITE_VINT_RESET:
        if (!(g_cpu.SR & 0x0004u)) {        /* Z=0 → bne.w $382 would jump */
            s_soft_reset_pending = 1;
            return 1;                       /* end the handler (implicit RTS) */
        }
        return 0;
    case AD_SITE_LOAD_JMP:
    case AD_SITE_GIVEUP_JMP:
    case AD_SITE_NOARMY_JMP:
        if (s_soft_reset_armed) {
            s_restart_pc = pc == AD_SITE_LOAD_JMP ? AD_MAP_LOOP_PC : AD_MAIN_MENU_PC;
            longjmp(s_soft_reset_jmp, 2);
        }
        return 0;
    case AD_MAP_START_PC:
    case 0x0117AAu: case 0x011860u: case 0x01186Cu: case 0x011876u: case 0x01189Eu:
    case 0x011AE6u: case 0x011BB0u: case 0x0119AAu: case 0x011A92u:
        if (ad_restart_hook(pc) == 2 && s_soft_reset_armed) {
            s_restart_pc = AD_MAP_START_PC;
            longjmp(s_soft_reset_jmp, 2);
        }
        return 0;
    case AD_SITE_WAIT_VBLANK:
        if (s_soft_reset_pending && s_soft_reset_armed) {
            s_soft_reset_pending = 0;
            longjmp(s_soft_reset_jmp, 1);
        }
        return 0;
    default:
        return 0;
    }
}
static void ad_call_vblank(void)      { recomp_call_addr(0x00518Cu); }
/* The H-int vector points into RAM; the game installs code there at runtime. */
static void ad_call_hblank(void)      { recomp_call_addr(0x00FFFF06u); }

/* ROM variant from the build (tools/build.sh → CMake): jp = Japan Rev A (E0D5E18A),
 * en = Nebelwurfer patch (72C5E589), tr = our translation (generated, 2 MiB). en changes no code;
 * tr only redirects the glyph lookup ($0081E0, docs/notes/translation-rom.md), so the same
 * binding applies to all three. */
#if !defined(AD_ROM_CRC32) || !defined(AD_ROM_SIZE)
#error "AD_ROM_CRC32/AD_ROM_SIZE missing – build via tools/build.sh"
#endif
#if AD_ROM_VARIANT_TR
#define AD_DISPLAY_NAME "Advanced Daisenryaku (English)"
#elif AD_ROM_VARIANT_EN
#define AD_DISPLAY_NAME "Advanced Daisenryaku (EN-Patch)"
#else
#define AD_DISPLAY_NAME "Advanced Daisenryaku"
#endif

const GameSpec g_game_spec = {
    .display_name           = AD_DISPLAY_NAME,
    .short_name             = "ADS",

    /* Exact ROM identity; other revisions have other addresses. */
    .expected_rom_crc32     = AD_ROM_CRC32,
    .expected_rom_size      = AD_ROM_SIZE,   /* 1 MiB, tr 3 MiB */

    /* No disassembly: discovery has gaps. Missing functions run in the
     * interpreter and end up as evidence in the miss logs for the next generation. */
    .tier3_floor_default    = 1,

    /* SRAM comes from the header ("RA", $200001–$20FFFF); tr: enabled in ad_call_entry_point. */

    .call_entry_point       = ad_call_entry_point,
    .call_vblank            = ad_call_vblank,
    .call_hblank            = ad_call_hblank,
    .resume_main_loop_pc    = 0u,      /* main loop still unknown */
    .save_resume_pc         = NULL,
    .dispatch_main_loop_pc  = 0u,
    .call_periodic          = NULL,

    .on_post_reset          = NULL,
    .on_frame_pre           = NULL,
    .on_frame_post          = NULL,
    .on_hblank              = NULL,

    .handle_arg             = NULL,
    .arg_usage              = NULL,
    .dispatch_override      = NULL,
    .instruction_hook       = ad_instruction_hook,

    .fill_frame_record      = NULL,
    .frame_record_version   = 0u,

    .commands               = NULL,
    .command_count          = 0,
};
