#define _DARWIN_C_SOURCE 1
#include "mmap_shim.h"

#undef mmap

#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

void *hrt_host_mmap(void *address, size_t length, int protection,
                    int flags, int descriptor, off_t offset) {
    if (descriptor < 0 || (flags & MAP_ANONYMOUS) != 0) {
        return mmap(address, length, protection, flags, descriptor, offset);
    }

    int anonymous_flags = flags;
    anonymous_flags &= ~MAP_SHARED;
    anonymous_flags |= MAP_PRIVATE | MAP_ANONYMOUS;
    int writable_protection = protection | PROT_WRITE;
    if (protection != PROT_NONE) writable_protection |= PROT_READ;

    void *mapping = mmap(address, length, writable_protection,
                         anonymous_flags, -1, 0);
    if (mapping == MAP_FAILED) return MAP_FAILED;

    unsigned char *cursor = mapping;
    size_t remaining = length;
    off_t position = offset;
    while (remaining != 0u) {
        ssize_t count = pread(descriptor, cursor, remaining, position);
        if (count < 0) {
            if (errno == EINTR) continue;
            int saved = errno;
            (void)munmap(mapping, length);
            errno = saved;
            return MAP_FAILED;
        }
        if (count == 0) break;
        cursor += (size_t)count;
        remaining -= (size_t)count;
        position += count;
    }
    if (remaining != 0u) memset(cursor, 0, remaining);

    if (mprotect(mapping, length, protection) != 0) {
        int saved = errno;
        (void)munmap(mapping, length);
        errno = saved;
        return MAP_FAILED;
    }
    return mapping;
}
