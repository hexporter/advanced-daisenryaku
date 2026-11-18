/* rompatch.h – the platform-neutral part of the release launchers (release/macos/launcher.c,
 * release/windows/launcher.c): CRC32, BPS patch (tools/bps.py writes it), and turning the
 * player's JP ROM into the translated ROM in the data folder. Included once per launcher.
 * Docs: docs/notes/release.md, docs/notes/windows.md
 */
#ifndef AD_ROMPATCH_H
#define AD_ROMPATCH_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#define RP_PATH_MAX 1024
/* rename() does not replace an existing file on Windows. */
static int replace_file(const char *from, const char *to)
{
    return MoveFileExA(from, to, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
}
#else
#include <limits.h>
#define RP_PATH_MAX PATH_MAX
static int replace_file(const char *from, const char *to) { return rename(from, to) == 0; }
#endif

static uint32_t crc32_of(const uint8_t *p, size_t n)
{
    static uint32_t table[256];
    if (!table[1])
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
    uint32_t c = 0xFFFFFFFFu;
    while (n--) c = table[(c ^ *p++) & 0xFF] ^ (c >> 8);
    return ~c;
}

static uint8_t *read_file(const char *path, size_t *len, size_t max)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    uint8_t *buf = NULL;
    if (fseek(f, 0, SEEK_END) == 0) {
        long n = ftell(f);
        if (n > 0 && (size_t)n <= max && fseek(f, 0, SEEK_SET) == 0 && (buf = malloc((size_t)n))) {
            if (fread(buf, 1, (size_t)n, f) == (size_t)n) *len = (size_t)n;
            else { free(buf); buf = NULL; }
        }
    }
    fclose(f);
    return buf;
}

static uint32_t le32(const uint8_t *p)
{
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

/* ---- BPS ------------------------------------------------------------------------------------ */

typedef struct {
    const uint8_t *data;
    size_t pos, end;          /* actions: [pos, end) */
    size_t source_size, target_size;
    uint32_t source_crc, target_crc;
    int bad;
} Bps;

static uint64_t bps_varint(Bps *b)
{
    uint64_t n = 0, shift = 1;
    for (;;) {
        if (b->pos >= b->end || shift > ((uint64_t)1 << 40)) { b->bad = 1; return 0; }
        uint8_t x = b->data[b->pos++];
        n += (uint64_t)(x & 0x7F) * shift;
        if (x & 0x80) return n;
        shift <<= 7;
        n += shift;
    }
}

static int bps_open(Bps *b, const uint8_t *patch, size_t len)
{
    memset(b, 0, sizeof *b);
    if (len < 19 || memcmp(patch, "BPS1", 4) != 0) return 0;
    if (crc32_of(patch, len - 4) != le32(patch + len - 4)) return 0;
    b->data = patch; b->pos = 4; b->end = len - 12;
    b->source_size = (size_t)bps_varint(b);
    b->target_size = (size_t)bps_varint(b);
    uint64_t meta = bps_varint(b);
    if (b->bad || meta > b->end - b->pos || b->target_size > (64u << 20)) return 0;
    b->pos += (size_t)meta;
    b->source_crc = le32(patch + len - 12);
    b->target_crc = le32(patch + len - 8);
    return 1;
}

/* Returns the target (malloc) or NULL. The caller has checked the source size and CRC32. */
static uint8_t *bps_apply(Bps *b, const uint8_t *src)
{
    uint8_t *out = malloc(b->target_size ? b->target_size : 1);
    size_t o = 0, src_rel = 0, tgt_rel = 0;
    if (!out) return NULL;
    while (b->pos < b->end && !b->bad) {
        uint64_t v = bps_varint(b);
        size_t n = (size_t)(v >> 2) + 1;
        int kind = (int)(v & 3);
        if (b->bad || n > b->target_size - o) { b->bad = 1; break; }
        if (kind == 0) {
            if (o + n > b->source_size) { b->bad = 1; break; }
            memcpy(out + o, src + o, n);
        } else if (kind == 1) {
            if (n > b->end - b->pos) { b->bad = 1; break; }
            memcpy(out + o, b->data + b->pos, n);
            b->pos += n;
        } else {
            uint64_t d = bps_varint(b);
            size_t *rel = kind == 2 ? &src_rel : &tgt_rel;
            size_t limit = kind == 2 ? b->source_size : o;
            size_t step = (size_t)(d >> 1);
            if (b->bad || (d & 1 ? step > *rel : step > limit - *rel)) { b->bad = 1; break; }
            *rel = d & 1 ? *rel - step : *rel + step;
            if (kind == 2) {
                if (n > b->source_size - *rel) { b->bad = 1; break; }
                memcpy(out + o, src + *rel, n);
            } else {
                if (*rel >= o) { b->bad = 1; break; }
                for (size_t i = 0; i < n; i++) out[o + i] = out[*rel + i];   /* may overlap */
            }
            *rel += n;
        }
        o += n;
    }
    if (b->bad || o != b->target_size || crc32_of(out, o) != b->target_crc) { free(out); return NULL; }
    return out;
}

/* ---- Files ---------------------------------------------------------------------------------- */

static int write_file(const char *path, const uint8_t *data, size_t len)
{
    char tmp[RP_PATH_MAX];
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    FILE *f = fopen(tmp, "wb");
    if (!f) return 0;
    int ok = fwrite(data, 1, len, f) == len;
    ok = fclose(f) == 0 && ok;
    if (ok) ok = replace_file(tmp, path);
    if (!ok) remove(tmp);
    return ok;
}

static int copy_file(const char *from, const char *to)
{
    size_t len = 0;
    uint8_t *data = read_file(from, &len, 16u << 20);
    int ok = data && write_file(to, data, len);
    free(data);
    return ok;
}

/* The patched ROM in the data folder is good when it is exactly the target of the patch. */
static int rom_is_current(const char *path, const Bps *b)
{
    size_t len = 0;
    uint8_t *rom = read_file(path, &len, 64u << 20);
    int ok = rom && len == b->target_size && crc32_of(rom, len) == b->target_crc;
    free(rom);
    return ok;
}

/* 1 = written, 0 = file is not the wanted ROM, -1 = wanted ROM but writing/patching failed */
static int patch_from(const char *source, const uint8_t *patch, size_t patch_len, const char *rom_path)
{
    Bps b;
    size_t len = 0;
    uint8_t *src = read_file(source, &len, 64u << 20);
    int rc = 0;
    if (src && bps_open(&b, patch, patch_len) && len == b.source_size &&
        crc32_of(src, len) == b.source_crc) {
        uint8_t *out = bps_apply(&b, src);
        rc = out && write_file(rom_path, out, b.target_size) ? 1 : -1;
        free(out);
    }
    free(src);
    return rc;
}

#endif
