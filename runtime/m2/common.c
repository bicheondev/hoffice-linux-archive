#include "hrt_m2.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

size_t g_host_page_size;
size_t g_guest_page_size = 4096u;
RuntimeState g_runtime;

void fatal(const char *message) {
    int saved = errno;
    if (saved != 0) {
        fprintf(stderr, "hrt-m2: %s: %s\n", message, strerror(saved));
    } else {
        fprintf(stderr, "hrt-m2: %s\n", message);
    }
    exit(1);
}

uintptr_t align_down(uintptr_t value, size_t alignment) {
    return value & ~((uintptr_t)alignment - 1u);
}

uintptr_t align_up(uintptr_t value, size_t alignment) {
    if (alignment == 0u || value > UINTPTR_MAX - (alignment - 1u)) {
        errno = 0;
        fatal("address alignment overflow");
    }
    return (value + alignment - 1u) & ~((uintptr_t)alignment - 1u);
}

void copy_checked(char *output, size_t output_size, const char *input,
                  const char *label) {
    size_t length = strlen(input);
    if (length + 1u > output_size) {
        errno = 0;
        fatal(label);
    }
    memcpy(output, input, length + 1u);
}

static int has_parent_component(const char *path) {
    const char *cursor = path;
    while (*cursor != '\0') {
        while (*cursor == '/') ++cursor;
        const char *start = cursor;
        while (*cursor != '\0' && *cursor != '/') ++cursor;
        size_t length = (size_t)(cursor - start);
        if (length == 2u && start[0] == '.' && start[1] == '.') return 1;
    }
    return 0;
}

void resolve_guest_path(const char *root, const char *guest_path,
                        char *output, size_t output_size) {
    if (root == NULL || root[0] == '\0' || guest_path == NULL ||
        guest_path[0] != '/' || has_parent_component(guest_path)) {
        errno = 0;
        fatal("invalid guest path");
    }
    size_t root_length = strlen(root);
    while (root_length > 1u && root[root_length - 1u] == '/') --root_length;
    size_t guest_length = strlen(guest_path);
    if (root_length > SIZE_MAX - guest_length - 1u ||
        root_length + guest_length + 1u > output_size) {
        errno = 0;
        fatal("resolved guest path is too long");
    }
    memcpy(output, root, root_length);
    memcpy(output + root_length, guest_path, guest_length + 1u);
}

void translate_guest_path(const char *guest_path,
                          char *host_path, size_t host_path_size) {
    if (guest_path == NULL || guest_path[0] == '\0' ||
        has_parent_component(guest_path)) {
        errno = EINVAL;
        return;
    }
    if (guest_path[0] == '/') {
        size_t root_length = strlen(g_runtime.root);
        while (root_length > 1u &&
               g_runtime.root[root_length - 1u] == '/') {
            --root_length;
        }
        size_t guest_length = strlen(guest_path);
        if (root_length > SIZE_MAX - guest_length - 1u ||
            root_length + guest_length + 1u > host_path_size) {
            errno = ENAMETOOLONG;
            return;
        }
        memcpy(host_path, g_runtime.root, root_length);
        memcpy(host_path + root_length, guest_path, guest_length + 1u);
        return;
    }

    size_t root_length = strlen(g_runtime.root);
    while (root_length > 1u && g_runtime.root[root_length - 1u] == '/') {
        --root_length;
    }
    size_t guest_length = strlen(guest_path);
    if (root_length > SIZE_MAX - guest_length - 2u ||
        root_length + guest_length + 2u > host_path_size) {
        errno = ENAMETOOLONG;
        return;
    }
    memcpy(host_path, g_runtime.root, root_length);
    host_path[root_length] = '/';
    memcpy(host_path + root_length + 1u, guest_path, guest_length + 1u);
}
