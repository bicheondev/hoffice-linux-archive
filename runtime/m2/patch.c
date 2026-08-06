#include "hrt_m2.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define HRT_MAX_PATCH_MAP_SIZE (1024u * 1024u)

static size_t patch_syscalls(unsigned char *start, size_t length) {
    size_t patched = 0;
    for (size_t index = 0; index + 1u < length; ++index) {
        if (start[index] == 0x0f && start[index + 1u] == 0x05) {
            start[index + 1u] = 0x0b;
            ++patched;
            ++index;
        }
    }
    return patched;
}

static int hex_value(unsigned char value) {
    if (value >= '0' && value <= '9') return (int)(value - '0');
    if (value >= 'a' && value <= 'f') return (int)(value - 'a') + 10;
    if (value >= 'A' && value <= 'F') return (int)(value - 'A') + 10;
    return -1;
}

static size_t patch_fs_prefixes(unsigned char *start, size_t length,
                                const char *host_path,
                                uint64_t file_offset) {
    if (host_path == NULL || host_path[0] == '\0') return 0;

    char sidecar[HRT_MAX_PATH];
    size_t path_length = strlen(host_path);
    static const char suffix[] = ".fspatch";
    if (path_length + sizeof(suffix) > sizeof(sidecar)) return 0;
    memcpy(sidecar, host_path, path_length);
    memcpy(sidecar + path_length, suffix, sizeof(suffix));

    int fd = open(sidecar, O_RDONLY);
    if (fd < 0) return 0;
    struct stat metadata;
    if (fstat(fd, &metadata) != 0 || metadata.st_size < 0 ||
        (uint64_t)metadata.st_size > HRT_MAX_PATCH_MAP_SIZE) {
        close(fd);
        return 0;
    }
    size_t map_size = (size_t)metadata.st_size;
    unsigned char *map = malloc(map_size + 1u);
    if (map == NULL) {
        close(fd);
        return 0;
    }
    size_t used = 0;
    while (used < map_size) {
        ssize_t count = read(fd, map + used, map_size - used);
        if (count < 0) {
            if (errno == EINTR) continue;
            free(map);
            close(fd);
            return 0;
        }
        if (count == 0) break;
        used += (size_t)count;
    }
    close(fd);
    map[used] = '\0';

    size_t patched = 0;
    size_t cursor = 0;
    while (cursor < used) {
        while (cursor < used &&
               (map[cursor] == ' ' || map[cursor] == '\t' ||
                map[cursor] == '\r' || map[cursor] == '\n')) {
            ++cursor;
        }
        if (cursor >= used) break;
        if (map[cursor] == '#') {
            while (cursor < used && map[cursor] != '\n') ++cursor;
            continue;
        }
        uint64_t value = 0;
        int digits = 0;
        if (cursor + 2u <= used && map[cursor] == '0' &&
            (map[cursor + 1u] == 'x' || map[cursor + 1u] == 'X')) {
            cursor += 2u;
        }
        while (cursor < used) {
            int nibble = hex_value(map[cursor]);
            if (nibble < 0) break;
            if (value > (UINT64_MAX - (uint64_t)nibble) / 16u) {
                digits = 0;
                break;
            }
            value = value * 16u + (uint64_t)nibble;
            ++cursor;
            ++digits;
        }
        while (cursor < used && map[cursor] != '\n') ++cursor;
        if (digits == 0 || value < file_offset) continue;
        uint64_t delta = value - file_offset;
        if (delta >= length) continue;
        if (start[delta] == 0x64) {
            start[delta] = 0x65;
            ++patched;
        }
    }
    free(map);
    return patched;
}

size_t patch_guest_code(void *start_pointer, size_t length,
                        const char *host_path, uint64_t file_offset,
                        size_t *fs_prefix_count) {
    unsigned char *start = start_pointer;
    size_t fs_count = patch_fs_prefixes(start, length,
                                        host_path, file_offset);
    size_t syscall_count = patch_syscalls(start, length);
    if (fs_prefix_count != NULL) *fs_prefix_count = fs_count;
    g_runtime.code_fs_patches += fs_count;
    g_runtime.code_syscall_patches += syscall_count;
    return syscall_count;
}

void record_fd_path(int fd, const char *host_path) {
    if (fd < 0 || fd >= HRT_MAX_TRACKED_FDS || host_path == NULL) return;
    size_t length = strlen(host_path);
    if (length + 1u > HRT_MAX_PATH) return;
    memcpy(g_runtime.fd_paths[fd], host_path, length + 1u);
}

const char *lookup_fd_path(int fd) {
    if (fd < 0 || fd >= HRT_MAX_TRACKED_FDS ||
        g_runtime.fd_paths[fd][0] == '\0') {
        return NULL;
    }
    return g_runtime.fd_paths[fd];
}

void clear_fd_path(int fd) {
    if (fd < 0 || fd >= HRT_MAX_TRACKED_FDS) return;
    g_runtime.fd_paths[fd][0] = '\0';
}

void copy_fd_path(int source_fd, int target_fd) {
    const char *source = lookup_fd_path(source_fd);
    if (source == NULL) {
        clear_fd_path(target_fd);
        return;
    }
    record_fd_path(target_fd, source);
}

void record_guest_mapping(uintptr_t start, size_t length, int fd,
                          uint64_t file_offset) {
    for (size_t index = 0; index < HRT_MAX_MAPPINGS; ++index) {
        if (!g_runtime.mappings[index].valid) {
            g_runtime.mappings[index].valid = 1;
            g_runtime.mappings[index].fd = fd;
            g_runtime.mappings[index].start = start;
            g_runtime.mappings[index].length = length;
            g_runtime.mappings[index].file_offset = file_offset;
            return;
        }
    }
}

void patch_guest_mappings(uintptr_t start, size_t length) {
    if (length == 0u || start > UINTPTR_MAX - length) return;
    uintptr_t end = start + length;
    for (size_t index = 0; index < HRT_MAX_MAPPINGS; ++index) {
        GuestMapping *mapping = &g_runtime.mappings[index];
        if (!mapping->valid || mapping->length == 0u ||
            mapping->start > UINTPTR_MAX - mapping->length) {
            continue;
        }
        uintptr_t mapping_end = mapping->start + mapping->length;
        uintptr_t overlap_start = start > mapping->start ? start : mapping->start;
        uintptr_t overlap_end = end < mapping_end ? end : mapping_end;
        if (overlap_start >= overlap_end) continue;
        uint64_t offset = mapping->file_offset +
            (uint64_t)(overlap_start - mapping->start);
        const char *path = lookup_fd_path(mapping->fd);
        size_t ignored_fs = 0;
        patch_guest_code((void *)overlap_start,
                         (size_t)(overlap_end - overlap_start),
                         path, offset, &ignored_fs);
    }
}
