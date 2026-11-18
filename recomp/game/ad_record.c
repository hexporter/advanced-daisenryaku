/*
 * ad_record.c – record the HD frame to a video from the running game (docs/notes/controls.md).
 *
 * Left stick click (L3) on any pad starts and stops; AD_REC=1 starts at boot (headless tests).
 * Needs ffmpeg (macOS: Homebrew; Windows: on PATH); AD_REC_CODEC overrides the encoder.
 * While recording, a red dot shows in the window's top-right corner (not in the video).
 * Output in build/video/ (in the data folder's video/ when GENESIS_USER_DIR is set: the Mac app,
 * the Windows release): rec-<time>.mp4 plus, for reading a bug frame by frame,
 *   rec-<time>.csv  one line per video frame: view, fine scroll, cursor, camera, pad
 *   rec-<time>.bin  per video frame: units $FFB000 ($1800), sprite table ($280),
 *                   $FFCD00 ($100), $FFD1C0 ($40) = $1BC0 bytes
 * Line n+1 of the csv and record n of the bin belong to video frame n. RAM is read at the V-int,
 * after the frame was drawn; the csv's b_* columns are what the zoomed map used for that frame.
 * Presentation only: nothing the game reads changes.
 */
#include "genesis_vdp.h"
#include "video/genesis_machine.h"

#include <SDL2/SDL.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#ifdef _WIN32
#include <direct.h>
#define popen  _popen
#define pclose _pclose
#define REC_MKDIR(d) _mkdir(d)
/* ffmpeg from PATH; libx264 runs everywhere, AD_REC_CODEC=h264_nvenc uses an NVIDIA GPU. */
#define REC_CMD "ffmpeg -loglevel error -y -f rawvideo -pix_fmt bgra -s %dx%d -r " REC_FPS \
                " -i - -c:v %s -b:v 30M -pix_fmt yuv420p \"%s.mp4\""
#define REC_CODEC_DEFAULT "libx264 -preset veryfast"
#define REC_PIPE_MODE "wb"                   /* binary: no CR/LF translation of the frames */
#else
#define REC_MKDIR(d) mkdir(d, 0755)
#define REC_CMD "PATH=/opt/homebrew/bin:/usr/local/bin:$PATH exec ffmpeg -loglevel error -y " \
                "-f rawvideo -pix_fmt bgra -s %dx%d -r " REC_FPS " -i - " \
                "-c:v %s -b:v 30M -pix_fmt yuv420p '%s.mp4'"
#define REC_CODEC_DEFAULT "h264_videotoolbox"
#define REC_PIPE_MODE "w"
#endif

extern uint8_t g_ram[0x010000];

const GVDP *ad_mapzoom_state(int out[10]);    /* ad_mapzoom.c */

#define REC_H 896
static int s_rec_w;                          /* frame width when the recording started */
#define REC_W s_rec_w
#define REC_FPS "59.922743"
#define REC_MAX_FRAMES (10 * 60 * 60)        /* a forgotten recording stops after 10 minutes */
#define REC_DIR "../video"                   /* development: build/video next to build/recomp-<v>/ */

static FILE *s_video, *s_csv, *s_bin;
static unsigned s_frames;
static uint32_t *s_rows;                     /* one frame, rows packed: one write per frame */

static void rec_stop(void)
{
    if (!s_video) return;
    pclose(s_video);
    fclose(s_csv);
    fclose(s_bin);
    s_video = s_csv = s_bin = NULL;
    fprintf(stderr, "[REC] stopped, %u frames\n", s_frames);
}

static void rec_start(void)
{
    char stamp[32], dir[1024], base[1100], cmd[2048], path[1200];
    time_t t = time(NULL);
    strftime(stamp, sizeof stamp, "%Y%m%d-%H%M%S", localtime(&t));
    const char *codec = getenv("AD_REC_CODEC");
    if (!codec || !*codec) codec = REC_CODEC_DEFAULT;
    /* The app / the Windows launcher set the data folder: videos go into its video/ folder. */
    const char *user = getenv("GENESIS_USER_DIR");
    if (user && *user) snprintf(dir, sizeof dir, "%s/video", user);
    else               snprintf(dir, sizeof dir, "%s", REC_DIR);
    REC_MKDIR(dir);
    snprintf(base, sizeof base, "%s/rec-%s", dir, stamp);
    snprintf(cmd, sizeof cmd, REC_CMD, REC_W, REC_H, codec, base);
#ifdef SIGPIPE
    signal(SIGPIPE, SIG_IGN);                /* ffmpeg gone must not end the game */
#endif
    s_video = popen(cmd, REC_PIPE_MODE);
    /* Unbuffered: the packed frame goes to the pipe in one write. Row by row through the C
     * runtime's 4 KiB buffer it took ~1400 pipe writes per frame – on Windows that halved the
     * game's speed while recording. */
    if (s_video) setvbuf(s_video, NULL, _IONBF, 0);
    free(s_rows);
    s_rows = malloc((size_t)REC_W * REC_H * sizeof *s_rows);
    snprintf(path, sizeof path, "%s.csv", base);
    s_csv = fopen(path, "w");
    snprintf(path, sizeof path, "%s.bin", base);
    s_bin = fopen(path, "wb");
    if (!s_video || !s_csv || !s_bin || !s_rows) {
        fprintf(stderr, "[REC] could not start (ffmpeg installed?)\n");
        if (s_video) pclose(s_video);
        if (s_csv) fclose(s_csv);
        if (s_bin) fclose(s_bin);
        s_video = s_csv = s_bin = NULL;
        return;
    }
    fputs("frame,cd14,cd16,cd1e,cd1f,cd20,cd21,cursor_obj_x,zoom_active,b_view_x,b_view_y,"
          "b_fine_x,b_fine_y,b_cam_x,b_cam_y,b_cursor_x,b_cursor_y,pad,b_spr_view_x,b_spr_fine_x\n", s_csv);
    s_frames = 0;
    fprintf(stderr, "[REC] recording to %s.mp4\n", base);
}

/* Bits: 0-3 dpad U D L R, 4-7 Xbox A B X Y; L3 reported separately. */
static unsigned read_pads(int *l3)
{
    static const SDL_GameControllerButton btn[8] = {
        SDL_CONTROLLER_BUTTON_DPAD_UP, SDL_CONTROLLER_BUTTON_DPAD_DOWN,
        SDL_CONTROLLER_BUTTON_DPAD_LEFT, SDL_CONTROLLER_BUTTON_DPAD_RIGHT,
        SDL_CONTROLLER_BUTTON_A, SDL_CONTROLLER_BUTTON_B,
        SDL_CONTROLLER_BUTTON_X, SDL_CONTROLLER_BUTTON_Y };
    unsigned mask = 0;
    *l3 = 0;
    for (int i = 0; i < SDL_NumJoysticks() && i < 4; i++) {
        if (!SDL_IsGameController(i)) continue;
        SDL_GameController *c = SDL_GameControllerOpen(i);   /* already open: reference only */
        if (!c) continue;
        if (SDL_GameControllerGetButton(c, SDL_CONTROLLER_BUTTON_LEFTSTICK)) *l3 = 1;
        for (unsigned b = 0; b < 8; b++)
            if (SDL_GameControllerGetButton(c, btn[b])) mask |= 1u << b;
        SDL_GameControllerClose(c);
    }
    return mask;
}

/* Called every V-int (ad_spec.c). */
void ad_record_vint(void)
{
    static int init, l3_down, pending;
    int l3;
    unsigned pad = read_pads(&l3);
    if (!init) {
        const char *e = getenv("AD_REC");
        init = 1;
        atexit(rec_stop);
        pending = e && atoi(e) > 0;
    }
    if (pending && g_hd_frame_w >= 1280 && !(g_hd_frame_w & 1) && g_hd_frame_h == REC_H) {
        pending = 0;                         /* AD_REC: start with the first HD frame */
        s_rec_w = g_hd_frame_w;
        rec_start();
    }
    if (l3 && !l3_down) {
        if (s_video) rec_stop();
        else if (g_hd_frame_w >= 1280 && !(g_hd_frame_w & 1) && g_hd_frame_h == REC_H) {
            s_rec_w = g_hd_frame_w;      /* 1280, or wider with side margins (GENESIS_HD_MARGIN) */
            rec_start();
        }
        else fprintf(stderr, "[REC] needs the HD frame (F10)\n");
    }
    l3_down = l3;
    if (!s_video || !g_hd_frame_request || g_hd_frame_w != REC_W || g_hd_frame_h != REC_H) return;

    for (int y = 0; y < REC_H; y++)          /* the frame's rows are GENESIS_HD_STRIDE apart */
        memcpy(s_rows + (size_t)y * REC_W, g_hd_frame + (size_t)y * GENESIS_HD_STRIDE,
               (size_t)REC_W * sizeof *s_rows);
    if (fwrite(s_rows, sizeof *s_rows, (size_t)REC_W * REC_H, s_video) != (size_t)REC_W * REC_H) {
        fprintf(stderr, "[REC] ffmpeg stopped accepting frames\n");
        rec_stop();
        return;
    }
    int b[10];
    const GVDP *v = ad_mapzoom_state(b);
    fprintf(s_csv, "%u,%d,%d,%u,%u,%u,%u,%u,%d,%d,%d,%d,%d,%d,%d,%d,%d,%u,%d,%d\n", s_frames,
            (int16_t)(g_ram[0xCD14] << 8 | g_ram[0xCD15]), (int16_t)(g_ram[0xCD16] << 8 | g_ram[0xCD17]),
            g_ram[0xCD1E], g_ram[0xCD1F], g_ram[0xCD20], g_ram[0xCD21],
            (unsigned)g_ram[0xD1D0] << 8 | g_ram[0xD1D1], v != NULL,
            b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], pad, b[8], b[9]);
    static uint8_t sat[0x280];
    if (v) {
        unsigned base = (unsigned)(v->reg[5] & 0x7Fu) << 9;
        for (unsigned i = 0; i < sizeof sat; i++) sat[i] = v->vram[(base + i) & 0xFFFFu];
    }
    fwrite(&g_ram[0xB000], 1, 0x1800, s_bin);
    fwrite(sat, 1, sizeof sat, s_bin);
    fwrite(&g_ram[0xCD00], 1, 0x100, s_bin);
    fwrite(&g_ram[0xD1C0], 1, 0x40, s_bin);

    for (int y = 16; y < 40; y++)            /* red dot: window only, the video is already written */
        for (int x = REC_W - 40; x < REC_W - 16; x++)
            g_hd_frame[(size_t)y * GENESIS_HD_STRIDE + (size_t)x] = 0xFFE02020u;
    if (++s_frames >= REC_MAX_FRAMES) rec_stop();
}
