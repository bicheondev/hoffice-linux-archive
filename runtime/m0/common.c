#include "hrt_m0.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

size_t g_page_size;

void fatal(const char *message) {
    int saved = errno;
    if (saved != 0) {
        fprintf(stderr, "hrt-m0: %s: %s\n", message, strerror(saved));
    } else {
        fprintf(stderr, "hrt-m0: %s\n", message);
    }
    exit(1);
}

uintptr_t align_down(uintptr_t value, size_t alignment) {
    return value & ~((uintptr_t)alignment - 1u);
}

uintptr_t align_up(uintptr_t value, size_t alignment) {
    return (value + alignment - 1u) & ~((uintptr_t)alignment - 1u);
}
