#define _DARWIN_C_SOURCE 1
#include "syscall_internal.h"

#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

static int ensure_fixed_region(uintptr_t address, size_t length) {
    if (address > UINTPTR_MAX - length) {
        errno = EOVERFLOW;
        return -1;
    }
    uintptr_t start = align_down(address, g_host_page_size);
    uintptr_t end = align_up(address + length, g_host_page_size);
    size_t span = (size_t)(end - start);
    if (mprotect((void *)start, span,
                 PROT_READ | PROT_WRITE | PROT_EXEC) == 0) {
        return 0;
    }
    void *mapping = mmap((void *)start, span,
                         PROT_READ | PROT_WRITE | PROT_EXEC,
                         MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0);
    return mapping == MAP_FAILED ? -1 : 0;
}

int64_t hrt_linux_mmap(uintptr_t requested, uint64_t raw_length,
                       uint64_t protection, uint64_t flags,
                       int fd, uint64_t file_offset) {
    if (raw_length == 0u || raw_length > SIZE_MAX) {
        return hrt_linux_failure(HRT_LINUX_EINVAL);
    }
    size_t length = (size_t)raw_length;
    if (requested > UINTPTR_MAX - length) {
        return hrt_linux_failure(75);
    }

    int fixed = (flags & (HRT_LINUX_MAP_FIXED |
                          HRT_LINUX_MAP_FIXED_NOREPLACE)) != 0u;
    unsigned char *mapping;
    if (fixed) {
        if (requested == 0u || ensure_fixed_region(requested, length) != 0) {
            return hrt_linux_failure(hrt_linux_errno(errno));
        }
        mapping = (unsigned char *)requested;
    } else {
        size_t span = (size_t)align_up(length, g_host_page_size);
        mapping = mmap(NULL, span,
                       PROT_READ | PROT_WRITE | PROT_EXEC,
                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (mapping == MAP_FAILED) {
            return hrt_linux_failure(hrt_linux_errno(errno));
        }
    }

    memset(mapping, 0, length);
    if ((flags & HRT_LINUX_MAP_ANONYMOUS) == 0u) {
        if (fd < 0) return hrt_linux_failure(HRT_LINUX_EBADF);
        size_t used = 0;
        while (used < length) {
            ssize_t count = pread(fd, mapping + used, length - used,
                                  (off_t)(file_offset + used));
            if (count < 0) {
                if (errno == EINTR) continue;
                return hrt_linux_failure(hrt_linux_errno(errno));
            }
            if (count == 0) break;
            used += (size_t)count;
        }
    }

    record_guest_mapping((uintptr_t)mapping, length, fd, file_offset);
    if ((protection & HRT_LINUX_PROT_EXEC) != 0u) {
        const char *path = lookup_fd_path(fd);
        size_t ignored_fs = 0;
        (void)patch_guest_code(mapping, length, path, file_offset,
                               &ignored_fs);
    }
    return (int64_t)(uintptr_t)mapping;
}

int64_t hrt_linux_brk(uintptr_t requested) {
    if (g_runtime.brk_base == 0u) {
        size_t span = (size_t)align_up(HRT_BRK_RESERVE,
                                      g_host_page_size);
        void *mapping = mmap(NULL, span, PROT_READ | PROT_WRITE,
                             MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (mapping == MAP_FAILED) return 0;
        g_runtime.brk_base = (uintptr_t)mapping;
        g_runtime.brk_current = g_runtime.brk_base;
        g_runtime.brk_limit = g_runtime.brk_base + span;
    }
    if (requested == 0u) return (int64_t)g_runtime.brk_current;
    if (requested >= g_runtime.brk_base &&
        requested <= g_runtime.brk_limit) {
        g_runtime.brk_current = requested;
    }
    return (int64_t)g_runtime.brk_current;
}
