#define _DARWIN_C_SOURCE 1
#include "hrt_m2.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define LINUX_AT_FDCWD (-100)

size_t g_page_size;
char g_rootfs[PATH_MAX];
char g_guest_program[PATH_MAX];

void fatal(const char *message) {
    if (errno != 0) {
        fprintf(stderr, "hrt-m2: %s: %s\n", message, strerror(errno));
    } else {
        fprintf(stderr, "hrt-m2: %s\n", message);
    }
    exit(1);
}

void fatal_detail(const char *message, const char *detail) {
    fprintf(stderr, "hrt-m2: %s: %s\n", message,
            detail != NULL ? detail : "(null)");
    exit(1);
}

uintptr_t align_down(uintptr_t value, size_t alignment) {
    return value & ~((uintptr_t)alignment - 1u);
}

uintptr_t align_up(uintptr_t value, size_t alignment) {
    return (value + (uintptr_t)alignment - 1u) & ~((uintptr_t)alignment - 1u);
}

long linux_error_from_host_errno(int value) {
    int linux_errno;
    switch (value) {
        case 0: linux_errno = 0; break;
        case EPERM: linux_errno = 1; break;
        case ENOENT: linux_errno = 2; break;
        case ESRCH: linux_errno = 3; break;
        case EINTR: linux_errno = 4; break;
        case EIO: linux_errno = 5; break;
        case ENXIO: linux_errno = 6; break;
        case E2BIG: linux_errno = 7; break;
        case ENOEXEC: linux_errno = 8; break;
        case EBADF: linux_errno = 9; break;
        case ECHILD: linux_errno = 10; break;
        case EAGAIN: linux_errno = 11; break;
        case ENOMEM: linux_errno = 12; break;
        case EACCES: linux_errno = 13; break;
        case EFAULT: linux_errno = 14; break;
        case EBUSY: linux_errno = 16; break;
        case EEXIST: linux_errno = 17; break;
        case EXDEV: linux_errno = 18; break;
        case ENODEV: linux_errno = 19; break;
        case ENOTDIR: linux_errno = 20; break;
        case EISDIR: linux_errno = 21; break;
        case EINVAL: linux_errno = 22; break;
        case ENFILE: linux_errno = 23; break;
        case EMFILE: linux_errno = 24; break;
        case ENOTTY: linux_errno = 25; break;
        case EFBIG: linux_errno = 27; break;
        case ENOSPC: linux_errno = 28; break;
        case ESPIPE: linux_errno = 29; break;
        case EROFS: linux_errno = 30; break;
        case EMLINK: linux_errno = 31; break;
        case EPIPE: linux_errno = 32; break;
        case EDOM: linux_errno = 33; break;
        case ERANGE: linux_errno = 34; break;
        case EDEADLK: linux_errno = 35; break;
        case ENAMETOOLONG: linux_errno = 36; break;
        case ENOLCK: linux_errno = 37; break;
        case ENOSYS: linux_errno = 38; break;
        case ENOTEMPTY: linux_errno = 39; break;
        case ELOOP: linux_errno = 40; break;
        case EOVERFLOW: linux_errno = 75; break;
        case EILSEQ: linux_errno = 84; break;
        default: linux_errno = 5; break; /* EIO */
    }
    return -(long)linux_errno;
}

static int path_is_safe(const char *path) {
    if (path == NULL || path[0] == '\0') return 0;
    if (strcmp(path, "..") == 0 || strncmp(path, "../", 3) == 0 ||
        strstr(path, "/../") != NULL ||
        (strlen(path) >= 3u && strcmp(path + strlen(path) - 3u, "/..") == 0)) {
        return 0;
    }
    return 1;
}

int set_runtime_paths(const char *rootfs, const char *guest_program) {
    if (rootfs == NULL || guest_program == NULL || guest_program[0] != '/') {
        errno = EINVAL;
        return -1;
    }
    char resolved[PATH_MAX];
    if (realpath(rootfs, resolved) == NULL) return -1;
    struct stat status;
    if (stat(resolved, &status) != 0) return -1;
    if (!S_ISDIR(status.st_mode)) {
        errno = ENOTDIR;
        return -1;
    }
    if (snprintf(g_rootfs, sizeof(g_rootfs), "%s", resolved) >=
        (int)sizeof(g_rootfs) ||
        snprintf(g_guest_program, sizeof(g_guest_program), "%s",
                 guest_program) >= (int)sizeof(g_guest_program)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    return 0;
}

int guest_path_to_host(char output[PATH_MAX], const char *guest_path) {
    if (output == NULL || !path_is_safe(guest_path)) {
        errno = EINVAL;
        return -1;
    }
    if (strcmp(guest_path, "/dev/null") == 0 ||
        strcmp(guest_path, "/dev/zero") == 0 ||
        strcmp(guest_path, "/dev/urandom") == 0 ||
        strcmp(guest_path, "/dev/random") == 0) {
        const char *host_path = strcmp(guest_path, "/dev/random") == 0
            ? "/dev/urandom" : guest_path;
        if (snprintf(output, PATH_MAX, "%s", host_path) >= PATH_MAX) {
            errno = ENAMETOOLONG;
            return -1;
        }
        return 0;
    }

    const char *effective = guest_path;
    if (strcmp(guest_path, "/proc/self/exe") == 0) effective = g_guest_program;
    if (effective[0] != '/') {
        errno = EINVAL;
        return -1;
    }
    int count = snprintf(output, PATH_MAX, "%s%s", g_rootfs, effective);
    if (count < 0 || count >= PATH_MAX) {
        errno = ENAMETOOLONG;
        return -1;
    }
    return 0;
}

int guest_at_path_to_host(char output[PATH_MAX], int guest_dirfd,
                          const char *guest_path) {
    if (guest_path == NULL || output == NULL || !path_is_safe(guest_path)) {
        errno = EINVAL;
        return -1;
    }
    if (guest_path[0] == '/') return guest_path_to_host(output, guest_path);
    if (guest_dirfd == LINUX_AT_FDCWD) {
        int count = snprintf(output, PATH_MAX, "%s/%s", g_rootfs, guest_path);
        if (count < 0 || count >= PATH_MAX) {
            errno = ENAMETOOLONG;
            return -1;
        }
        return 0;
    }
    if (snprintf(output, PATH_MAX, "%s", guest_path) >= PATH_MAX) {
        errno = ENAMETOOLONG;
        return -1;
    }
    return 0;
}
