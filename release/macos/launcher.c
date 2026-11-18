/* Launcher of the Mac app (Contents/MacOS/"Advanced Daisenryaku"); built by tools/release.sh.
 *
 * The app ships without a ROM. On the first start the player picks their own dump of the Japanese
 * cartridge; the launcher applies Contents/Resources/translation.bps (BPS patch, tools/bps.py)
 * and keeps the result in the data folder. Then it starts the game (Contents/MacOS/ADRecomp)
 * with that folder as the place for save games and settings.
 *
 *   data folder  ~/Library/Application Support/Advanced Daisenryaku   (AD_USER_DIR overrides)
 *   AD_ROM       path of the JP ROM, instead of the file dialog (tests)
 *   arguments    are passed on to the game (e.g. --max-frames 600)
 *
 * Docs: docs/notes/release.md
 */
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../common/rompatch.h"

#define APP_NAME   "Advanced Daisenryaku"
#define ROM_NAME   "ad-tr.md"          /* the save game is named after it: ad-tr.srm */
#define ROM_WANTED "Advanced Daisenryaku - Deutsch Dengeki Sakusen (Japan, Rev A)"

/* ---- Dialogs (osascript; no text of ours or of the player is interpolated into a script) ----- */

static int run_capture(const char *cmd, char *out, size_t max)
{
    FILE *p = popen(cmd, "r");
    if (!p) return 0;
    out[0] = 0;
    char *got = fgets(out, (int)max, p);
    int rc = pclose(p);
    size_t n = strlen(out);
    while (n && (out[n - 1] == '\n' || out[n - 1] == '\r')) out[--n] = 0;
    return got && rc == 0 && n;
}

/* The texts travel in the environment and reach the script as arguments ("$AD_MSG" is expanded
   by the shell, never parsed as script), so they need no quoting. Not `system attribute`: it
   reads the environment as MacRoman, which garbles UTF-8 ("…" became ",Ä¶") and made the
   returned button differ from `ok`. */
static int alert(const char *message, const char *ok, const char *cancel)
{
    char out[64];
    fprintf(stderr, "[launcher] %s\n", message);
    setenv("AD_MSG", message, 1);
    setenv("AD_OK", ok, 1);
    setenv("AD_CANCEL", cancel ? cancel : "", 1);
    return run_capture(
        "/usr/bin/osascript -e 'on run argv'"
        " -e 'set m to item 1 of argv' -e 'set a to item 2 of argv' -e 'set c to item 3 of argv'"
        " -e 'if c is \"\" then' -e 'set b to {a}' -e 'else' -e 'set b to {c, a}' -e 'end if'"
        " -e 'button returned of (display dialog m with title \"" APP_NAME "\""
        " buttons b default button a)' -e 'end run'"
        " \"$AD_MSG\" \"$AD_OK\" \"$AD_CANCEL\" 2>/dev/null", out, sizeof out)
        && strcmp(out, ok) == 0;
}

static int pick_rom(char *out, size_t max)
{
    return run_capture(
        "/usr/bin/osascript -e 'POSIX path of (choose file with prompt"
        " \"Select your ROM of " ROM_WANTED "\")' 2>/dev/null", out, max);
}

/* ---- Files ---------------------------------------------------------------------------------- */

static int exists(const char *path) { struct stat st; return stat(path, &st) == 0; }

static int mkdirs(const char *path)
{
    char tmp[PATH_MAX];
    snprintf(tmp, sizeof tmp, "%s", path);
    for (char *p = tmp + 1; *p; p++)
        if (*p == '/') { *p = 0; mkdir(tmp, 0755); *p = '/'; }
    return mkdir(tmp, 0755) == 0 || errno == EEXIST;
}

int main(int argc, char **argv)
{
    char exe[PATH_MAX], real[PATH_MAX], macos[PATH_MAX], res[PATH_MAX], data[PATH_MAX];
    char path[PATH_MAX + 64], rom[PATH_MAX + 64], source_note[PATH_MAX + 64];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) return 1;
    *strrchr(real, '/') = 0;
    snprintf(macos, sizeof macos, "%s", real);
    snprintf(res, sizeof res, "%s/../Resources", real);

    const char *override = getenv("AD_USER_DIR"), *home = getenv("HOME");
    if (override && override[0] == '/') snprintf(data, sizeof data, "%s", override);
    else if (home && home[0] == '/')
        snprintf(data, sizeof data, "%s/Library/Application Support/" APP_NAME, home);
    else return 1;
    if (!mkdirs(data)) {
        alert("The data folder could not be created.", "Quit", NULL);
        return 1;
    }

    /* Console output of launcher and game goes to run.log when there is no terminal (Finder). */
    if (!isatty(STDERR_FILENO)) {
        char prev[PATH_MAX + 64];
        snprintf(path, sizeof path, "%s/run.log", data);
        snprintf(prev, sizeof prev, "%s/run.prev.log", data);
        rename(path, prev);
        int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) { dup2(fd, STDOUT_FILENO); dup2(fd, STDERR_FILENO); close(fd); }
    }

    snprintf(path, sizeof path, "%s/translation.bps", res);
    size_t patch_len = 0;
    uint8_t *patch = read_file(path, &patch_len, 16u << 20);
    Bps b;
    if (!patch || !bps_open(&b, patch, patch_len)) {
        alert("The app is damaged (translation patch missing). Please download it again.", "Quit", NULL);
        return 1;
    }

    snprintf(rom, sizeof rom, "%s/" ROM_NAME, data);
    snprintf(source_note, sizeof source_note, "%s/rom-source.txt", data);
    if (!rom_is_current(rom, &b)) {
        /* After an update of the app the patch is a new one: try the ROM picked last time first. */
        char source[PATH_MAX] = "";
        int done = 0;
        const char *env_rom = getenv("AD_ROM");
        if (env_rom && *env_rom) {
            done = patch_from(env_rom, patch, patch_len, rom);
            if (done != 1) { fprintf(stderr, "[launcher] AD_ROM is not usable: %s\n", env_rom); return 1; }
            snprintf(source, sizeof source, "%s", env_rom);
        } else {
            FILE *f = fopen(source_note, "r");
            if (f) {
                if (fgets(source, sizeof source, f)) source[strcspn(source, "\r\n")] = 0;
                else source[0] = 0;
                fclose(f);
                if (source[0]) done = patch_from(source, patch, patch_len, rom) == 1;
            }
            if (!done && !alert(
                    "This app needs your own ROM file of the Japanese Mega Drive game\n"
                    ROM_WANTED ".\n\n"
                    "It is asked for once. The English translation is applied to a copy in the "
                    "app's data folder; your file is not changed.", "Select ROM…", "Quit"))
                return 0;
            while (!done) {
                if (!pick_rom(source, sizeof source)) return 0;      /* cancelled */
                int rc = patch_from(source, patch, patch_len, rom);
                if (rc == 1) { done = 1; break; }
                if (rc < 0) {
                    alert("The ROM could not be prepared (data folder not writable?).", "Quit", NULL);
                    return 1;
                }
                char msg[400];
                snprintf(msg, sizeof msg,
                    "This is not the expected ROM.\n\nNeeded: " ROM_WANTED ",\n"
                    "%u bytes, CRC32 %08X (plain .md/.bin dump, not zipped).",
                    (unsigned)b.source_size, (unsigned)b.source_crc);
                if (!alert(msg, "Select another…", "Quit")) return 0;
            }
        }
        FILE *f = fopen(source_note, "w");
        if (f) { fprintf(f, "%s\n", source); fclose(f); }
        fprintf(stderr, "[launcher] ROM prepared: %s (CRC32 %08X)\n", rom, (unsigned)b.target_crc);
    }
    free(patch);

    /* Controller layout etc.: seeded once, afterwards the player's file. */
    snprintf(path, sizeof path, "%s/settings.ini", data);
    if (!exists(path)) {
        char from[PATH_MAX + 64];
        snprintf(from, sizeof from, "%s/settings.ini", res);
        if (exists(from)) copy_file(from, path);
    }

    setenv("GENESIS_USER_DIR", data, 1);
    setenv("GENESIS_NO_LAUNCHER", "1", 1);
    snprintf(path, sizeof path, "%s/pack.bin", res);
    if (!getenv("GENESIS_HD_PACK") && exists(path)) setenv("GENESIS_HD_PACK", path, 1);
    /* 16:9 as tools/run.sh: side margins of 39 screen px with the HD frame (docs/notes/map.md).
     * Without the HD pack the picture stays 4:3. GENESIS_HD_MARGIN set by the user wins. */
    if (getenv("GENESIS_HD_PACK") && !getenv("GENESIS_HD_MARGIN")) setenv("GENESIS_HD_MARGIN", "39", 1);
    unsetenv("AD_MSG"); unsetenv("AD_OK"); unsetenv("AD_CANCEL");
    if (chdir(data) != 0) return 1;

    char game[PATH_MAX + 64];
    snprintf(game, sizeof game, "%s/ADRecomp", macos);
    char **args = calloc((size_t)argc + 2, sizeof *args);
    if (!args) return 1;
    int n = 0;
    args[n++] = game;
    for (int i = 1; i < argc; i++)
        if (strncmp(argv[i], "-psn_", 5) != 0) args[n++] = argv[i];   /* old Finder argument */
    args[n++] = rom;
    args[n] = NULL;
    fflush(NULL);
    execv(game, args);
    alert("The game could not be started (app damaged?).", "Quit", NULL);
    return 1;
}
