/* Launcher of the Windows build ("Advanced Daisenryaku.exe" next to ADRecomp.exe); built by
 * recomp/CMakeLists.txt (target ADLauncher, Windows only) and packaged by tools/release_windows.sh.
 *
 * Same job as the Mac launcher (release/macos/launcher.c): the folder ships without a ROM. On the
 * first start the player picks their own dump of the Japanese cartridge; the launcher applies
 * translation.bps (next to the exe) and keeps the result in the data folder. Then it starts
 * ADRecomp.exe with that folder as the place for save games and settings, waits for it and
 * returns its exit code.
 *
 *   data folder  %APPDATA%\Advanced Daisenryaku   (AD_USER_DIR overrides)
 *   AD_ROM       path of the JP ROM, instead of the file dialog (tests)
 *   arguments    are passed on to the game (e.g. --max-frames 600)
 *
 * Paths are UTF-8 throughout: the executables carry a manifest with the UTF-8 code page
 * (release/windows/utf8.manifest), so the A functions and fopen take UTF-8.
 * A GUI program (no console window). Without a console the output of launcher and game goes to
 * run.log in the data folder.
 *
 * Docs: docs/notes/windows.md
 */
#include "../common/rompatch.h"

#include <commdlg.h>
#include <direct.h>
#include <errno.h>
#include <io.h>
#include <sys/stat.h>

#define APP_NAME   "Advanced Daisenryaku"
#define ROM_NAME   "ad-tr.md"          /* the save game is named after it: ad-tr.srm */
#define ROM_WANTED "Advanced Daisenryaku - Deutsch Dengeki Sakusen (Japan, Rev A)"

/* ---- Dialogs -------------------------------------------------------------------------------- */

/* OK/Cancel box; returns 1 for OK. Button labels are Windows' own (OK, Cancel). */
static int alert(const char *message, int with_cancel)
{
    fprintf(stderr, "[launcher] %s\n", message);
    fflush(stderr);
    if (getenv("AD_ROM")) return 0;                     /* tests: never wait for a click */
    UINT type = (with_cancel ? MB_OKCANCEL : MB_OK) | MB_ICONINFORMATION | MB_SETFOREGROUND;
    return MessageBoxA(NULL, message, APP_NAME, type) == IDOK;
}

static int pick_rom(char *out, size_t max)
{
    OPENFILENAMEA ofn;
    memset(&ofn, 0, sizeof ofn);
    out[0] = 0;
    ofn.lStructSize = sizeof ofn;
    ofn.lpstrFilter = "Mega Drive ROM (*.md;*.bin;*.gen;*.smd)\0*.md;*.bin;*.gen;*.smd\0All files\0*.*\0";
    ofn.lpstrFile = out;
    ofn.nMaxFile = (DWORD)max;
    ofn.lpstrTitle = "Select your ROM of " ROM_WANTED;
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
    return GetOpenFileNameA(&ofn) && out[0];
}

/* ---- Files ---------------------------------------------------------------------------------- */

static int exists(const char *path) { struct _stat st; return _stat(path, &st) == 0; }

static int mkdirs(const char *path)
{
    char tmp[RP_PATH_MAX];
    snprintf(tmp, sizeof tmp, "%s", path);
    for (char *p = tmp + 3; *p; p++)                    /* after "C:\" */
        if (*p == '\\' || *p == '/') { char c = *p; *p = 0; _mkdir(tmp); *p = c; }
    return _mkdir(tmp) == 0 || errno == EEXIST;
}

static int is_absolute(const char *p)
{
    return p && ((((p[0] | 0x20) >= 'a' && (p[0] | 0x20) <= 'z') && p[1] == ':' &&
                  (p[2] == '\\' || p[2] == '/')) || (p[0] == '\\' && p[1] == '\\'));
}

/* ---- Process -------------------------------------------------------------------------------- */

/* Append one argument to a command line, quoted the way the MSVC runtime splits it again. */
static void append_arg(char *cmd, size_t max, const char *arg)
{
    size_t n = strlen(cmd);
#define PUT(c) do { if (n + 2 < max) cmd[n++] = (c); } while (0)
    if (n) PUT(' ');
    PUT('"');
    for (const char *p = arg;; p++) {
        size_t slashes = 0;
        while (*p == '\\') { slashes++; p++; }
        if (!*p) {                                      /* double them before the closing quote */
            for (size_t i = 0; i < 2 * slashes; i++) PUT('\\');
            break;
        }
        if (*p == '"') {                                /* double them, then an escaped quote */
            for (size_t i = 0; i < 2 * slashes + 1; i++) PUT('\\');
        } else {
            for (size_t i = 0; i < slashes; i++) PUT('\\');
        }
        PUT(*p);
    }
    PUT('"');
#undef PUT
    cmd[n] = 0;
}

static int has_console_output(void)
{
    HANDLE h = GetStdHandle(STD_ERROR_HANDLE);
    return h != NULL && h != INVALID_HANDLE_VALUE;
}

int main(int argc, char **argv)
{
    char exe[RP_PATH_MAX], dir[RP_PATH_MAX], data[RP_PATH_MAX];
    char path[RP_PATH_MAX + 64], rom[RP_PATH_MAX + 64], source_note[RP_PATH_MAX + 64];
    DWORD got = GetModuleFileNameA(NULL, exe, sizeof exe);
    if (got == 0 || got >= sizeof exe) return 1;
    snprintf(dir, sizeof dir, "%s", exe);
    char *slash = strrchr(dir, '\\');
    if (!slash) return 1;
    *slash = 0;

    const char *override = getenv("AD_USER_DIR"), *appdata = getenv("APPDATA");
    if (is_absolute(override)) snprintf(data, sizeof data, "%s", override);
    else if (is_absolute(appdata)) snprintf(data, sizeof data, "%s\\" APP_NAME, appdata);
    else return 1;
    if (!mkdirs(data)) {
        alert("The data folder could not be created.", 0);
        return 1;
    }

    /* Console output of launcher and game goes to run.log when there is no console (Explorer). */
    int to_log = !has_console_output();
    if (to_log) {
        char prev[RP_PATH_MAX + 64];
        snprintf(path, sizeof path, "%s\\run.log", data);
        snprintf(prev, sizeof prev, "%s\\run.prev.log", data);
        replace_file(path, prev);
        if (!freopen(path, "w", stderr)) to_log = 0;
        else setvbuf(stderr, NULL, _IONBF, 0);
    }

    snprintf(path, sizeof path, "%s\\translation.bps", dir);
    size_t patch_len = 0;
    uint8_t *patch = read_file(path, &patch_len, 16u << 20);
    Bps b;
    if (!patch || !bps_open(&b, patch, patch_len)) {
        alert("The game folder is damaged (translation patch missing). Please download it again.", 0);
        return 1;
    }

    snprintf(rom, sizeof rom, "%s\\" ROM_NAME, data);
    snprintf(source_note, sizeof source_note, "%s\\rom-source.txt", data);
    if (!rom_is_current(rom, &b)) {
        /* After an update the patch is a new one: try the ROM picked last time first. */
        char source[RP_PATH_MAX] = "";
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
                    "This game needs your own ROM file of the Japanese Mega Drive game\n"
                    ROM_WANTED ".\n\n"
                    "It is asked for once. The English translation is applied to a copy in the "
                    "game's data folder; your file is not changed.\n\nOK: select the ROM file.", 1))
                return 0;
            while (!done) {
                if (!pick_rom(source, sizeof source)) return 0;      /* cancelled */
                int rc = patch_from(source, patch, patch_len, rom);
                if (rc == 1) { done = 1; break; }
                if (rc < 0) {
                    alert("The ROM could not be prepared (data folder not writable?).", 0);
                    return 1;
                }
                char msg[400];
                snprintf(msg, sizeof msg,
                    "This is not the expected ROM.\n\nNeeded: " ROM_WANTED ",\n"
                    "%u bytes, CRC32 %08X (plain .md/.bin dump, not zipped).\n\nOK: select another file.",
                    (unsigned)b.source_size, (unsigned)b.source_crc);
                if (!alert(msg, 1)) return 0;
            }
        }
        FILE *f = fopen(source_note, "w");
        if (f) { fprintf(f, "%s\n", source); fclose(f); }
        fprintf(stderr, "[launcher] ROM prepared: %s (CRC32 %08X)\n", rom, (unsigned)b.target_crc);
    }
    free(patch);

    /* Controller layout etc.: seeded once, afterwards the player's file. */
    snprintf(path, sizeof path, "%s\\settings.ini", data);
    if (!exists(path)) {
        char from[RP_PATH_MAX + 64];
        snprintf(from, sizeof from, "%s\\settings.ini", dir);
        if (exists(from)) copy_file(from, path);
    }

    SetEnvironmentVariableA("GENESIS_USER_DIR", data);
    SetEnvironmentVariableA("GENESIS_NO_LAUNCHER", "1");
    snprintf(path, sizeof path, "%s\\pack.bin", dir);
    int hd = getenv("GENESIS_HD_PACK") != NULL;
    if (!hd && exists(path)) { SetEnvironmentVariableA("GENESIS_HD_PACK", path); hd = 1; }
    /* 16:9 as tools/run.sh: side margins of 39 screen px with the HD frame (docs/notes/map.md).
     * Without the HD pack the picture stays 4:3. GENESIS_HD_MARGIN set by the user wins. */
    if (hd && !getenv("GENESIS_HD_MARGIN")) SetEnvironmentVariableA("GENESIS_HD_MARGIN", "39");
    if (!SetCurrentDirectoryA(data)) return 1;

    char game[RP_PATH_MAX + 64];
    snprintf(game, sizeof game, "%s\\ADRecomp.exe", dir);
    static char cmd[32768];
    cmd[0] = 0;
    append_arg(cmd, sizeof cmd, game);
    for (int i = 1; i < argc; i++) append_arg(cmd, sizeof cmd, argv[i]);
    append_arg(cmd, sizeof cmd, rom);

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof si);
    memset(&pi, 0, sizeof pi);
    si.cb = sizeof si;
    /* The game gets the launcher's output: run.log without a console, else the console or
     * whatever the caller redirected to (tools/release_windows.sh's smoke test). */
    HANDLE log = to_log ? (HANDLE)_get_osfhandle(_fileno(stderr)) : INVALID_HANDLE_VALUE;
    HANDLE std[3] = { GetStdHandle(STD_INPUT_HANDLE),
                      to_log ? log : GetStdHandle(STD_OUTPUT_HANDLE),
                      to_log ? log : GetStdHandle(STD_ERROR_HANDLE) };
    for (int i = 0; i < 3; i++) {
        if (std[i] == INVALID_HANDLE_VALUE) std[i] = NULL;
        if (std[i]) SetHandleInformation(std[i], HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    }
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = std[0];
    si.hStdOutput = std[1];
    si.hStdError = std[2];
    DWORD flags = to_log ? CREATE_NO_WINDOW : 0;        /* the game is a console program */
    fflush(NULL);
    if (!CreateProcessA(game, cmd, NULL, NULL, TRUE, flags, NULL, data, &si, &pi)) {
        fprintf(stderr, "[launcher] CreateProcess failed (%lu): %s\n", (unsigned long)GetLastError(), game);
        alert("The game could not be started (ADRecomp.exe missing?).", 0);
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD rc = 1;
    GetExitCodeProcess(pi.hProcess, &rc);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)rc;
}
