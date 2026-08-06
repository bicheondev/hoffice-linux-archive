#define _DARWIN_C_SOURCE 1
#include "syscall_internal.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int hrt_linux_errno(int host_error) {
    switch (host_error) {
        case 0: return 0;
        case EPERM: return 1;
        case ENOENT: return 2;
        case ESRCH: return 3;
        case EINTR: return 4;
        case EIO: return 5;
        case ENXIO: return 6;
        case E2BIG: return 7;
        case ENOEXEC: return 8;
        case EBADF: return 9;
        case ECHILD: return 10;
        case EAGAIN: return 11;
        case ENOMEM: return 12;
        case EACCES: return 13;
        case EFAULT: return 14;
        case EBUSY: return 16;
        case EEXIST: return 17;
        case EXDEV: return 18;
        case ENODEV: return 19;
        case ENOTDIR: return 20;
        case EISDIR: return 21;
        case EINVAL: return 22;
        case ENFILE: return 23;
        case EMFILE: return 24;
        case ENOTTY: return 25;
        case ETXTBSY: return 26;
        case EFBIG: return 27;
        case ENOSPC: return 28;
        case ESPIPE: return 29;
        case EROFS: return 30;
        case EMLINK: return 31;
        case EPIPE: return 32;
        case EDOM: return 33;
        case ERANGE: return 34;
        case EDEADLK: return 35;
        case ENAMETOOLONG: return 36;
#ifdef ENOSYS
        case ENOSYS: return 38;
#endif
#ifdef EOVERFLOW
        case EOVERFLOW: return 75;
#endif
#ifdef ENOTSUP
        case ENOTSUP: return 95;
#endif
#if defined(EOPNOTSUPP) && (!defined(ENOTSUP) || EOPNOTSUPP != ENOTSUP)
        case EOPNOTSUPP: return 95;
#endif
#ifdef ETIMEDOUT
        case ETIMEDOUT: return 110;
#endif
        default: return 5;
    }
}

int64_t hrt_linux_failure(int linux_error) {
    return -(int64_t)linux_error;
}

int64_t hrt_host_result(long result) {
    return result == -1 ? hrt_linux_failure(hrt_linux_errno(errno))
                        : (int64_t)result;
}

void hrt_log_unsupported(uint64_t number) {
    char buffer[96];
    static const char prefix[] = "hrt-m2: unsupported Linux syscall ";
    size_t used = sizeof(prefix) - 1u;
    memcpy(buffer, prefix, used);
    char digits[24];
    size_t count = 0;
    do {
        digits[count++] = (char)('0' + number % 10u);
        number /= 10u;
    } while (number != 0u && count < sizeof(digits));
    while (count != 0u && used < sizeof(buffer) - 1u) {
        buffer[used++] = digits[--count];
    }
    buffer[used++] = '\n';
    (void)write(STDERR_FILENO, buffer, used);
}

int hrt_translate_open_flags(uint64_t flags) {
    int result = 0;
    switch (flags & 3u) {
        case 0: result |= O_RDONLY; break;
        case 1: result |= O_WRONLY; break;
        case 2: result |= O_RDWR; break;
        default: break;
    }
    if ((flags & 0x40u) != 0u) result |= O_CREAT;
    if ((flags & 0x80u) != 0u) result |= O_EXCL;
    if ((flags & 0x200u) != 0u) result |= O_TRUNC;
    if ((flags & 0x400u) != 0u) result |= O_APPEND;
    if ((flags & 0x800u) != 0u) result |= O_NONBLOCK;
#ifdef O_DIRECTORY
    if ((flags & 0x10000u) != 0u) result |= O_DIRECTORY;
#endif
#ifdef O_NOFOLLOW
    if ((flags & 0x20000u) != 0u) result |= O_NOFOLLOW;
#endif
#ifdef O_CLOEXEC
    if ((flags & 0x80000u) != 0u) result |= O_CLOEXEC;
#endif
    return result;
}

int hrt_translate_path_checked(const char *guest_path,
                               char *host_path, size_t host_path_size) {
    errno = 0;
    translate_guest_path(guest_path, host_path, host_path_size);
    return errno == 0 ? 0 : -1;
}

int64_t hrt_linux_open_path(const char *guest_path, uint64_t flags,
                            uint64_t mode) {
    if (guest_path == NULL) return hrt_linux_failure(HRT_LINUX_EFAULT);
    char host_path[HRT_MAX_PATH];
    if (hrt_translate_path_checked(guest_path, host_path,
                                   sizeof(host_path)) != 0) {
        return hrt_linux_failure(hrt_linux_errno(errno));
    }
    int fd = open(host_path, hrt_translate_open_flags(flags), (mode_t)mode);
    if (fd < 0) return hrt_linux_failure(hrt_linux_errno(errno));
    record_fd_path(fd, host_path);
    return fd;
}

static void translate_stat(const struct stat *source, HrtLinuxStat *target) {
    memset(target, 0, sizeof(*target));
    target->st_dev = (uint64_t)source->st_dev;
    target->st_ino = (uint64_t)source->st_ino;
    target->st_nlink = (uint64_t)source->st_nlink;
    target->st_mode = (uint32_t)source->st_mode;
    target->st_uid = (uint32_t)source->st_uid;
    target->st_gid = (uint32_t)source->st_gid;
    target->st_rdev = (uint64_t)source->st_rdev;
    target->st_size = (int64_t)source->st_size;
    target->st_blksize = (int64_t)source->st_blksize;
    target->st_blocks = (int64_t)source->st_blocks;
    target->st_atime = (int64_t)source->st_atimespec.tv_sec;
    target->st_atime_nsec = (int64_t)source->st_atimespec.tv_nsec;
    target->st_mtime = (int64_t)source->st_mtimespec.tv_sec;
    target->st_mtime_nsec = (int64_t)source->st_mtimespec.tv_nsec;
    target->st_ctime = (int64_t)source->st_ctimespec.tv_sec;
    target->st_ctime_nsec = (int64_t)source->st_ctimespec.tv_nsec;
}

int64_t hrt_linux_stat_path(const char *guest_path, HrtLinuxStat *output,
                            int nofollow) {
    if (guest_path == NULL || output == NULL) {
        return hrt_linux_failure(HRT_LINUX_EFAULT);
    }
    char host_path[HRT_MAX_PATH];
    if (hrt_translate_path_checked(guest_path, host_path,
                                   sizeof(host_path)) != 0) {
        return hrt_linux_failure(hrt_linux_errno(errno));
    }
    struct stat metadata;
    int result = nofollow ? lstat(host_path, &metadata)
                          : stat(host_path, &metadata);
    if (result != 0) return hrt_linux_failure(hrt_linux_errno(errno));
    translate_stat(&metadata, output);
    return 0;
}

int64_t hrt_linux_fstat(int fd, HrtLinuxStat *output) {
    if (output == NULL) return hrt_linux_failure(HRT_LINUX_EFAULT);
    struct stat metadata;
    if (fstat(fd, &metadata) != 0) {
        return hrt_linux_failure(hrt_linux_errno(errno));
    }
    translate_stat(&metadata, output);
    return 0;
}

int64_t hrt_linux_newfstatat(int dirfd, const char *guest_path,
                             HrtLinuxStat *output, uint64_t flags) {
    if (guest_path == NULL || output == NULL) {
        return hrt_linux_failure(HRT_LINUX_EFAULT);
    }
    if (guest_path[0] == '\0' &&
        (flags & HRT_LINUX_AT_EMPTY_PATH) != 0u) {
        return hrt_linux_fstat(dirfd, output);
    }
    if (guest_path[0] != '/' && dirfd != HRT_LINUX_AT_FDCWD) {
        return hrt_linux_failure(HRT_LINUX_EOPNOTSUPP);
    }
    return hrt_linux_stat_path(guest_path, output,
        (flags & HRT_LINUX_AT_SYMLINK_NOFOLLOW) != 0u);
}

int64_t hrt_linux_readlink_path(const char *guest_path,
                                char *buffer, size_t size) {
    if (guest_path == NULL || buffer == NULL) {
        return hrt_linux_failure(HRT_LINUX_EFAULT);
    }
    if (strcmp(guest_path, "/proc/self/exe") == 0) {
        size_t length = strlen(g_runtime.guest_program);
        if (length > size) length = size;
        memcpy(buffer, g_runtime.guest_program, length);
        return (int64_t)length;
    }
    char host_path[HRT_MAX_PATH];
    if (hrt_translate_path_checked(guest_path, host_path,
                                   sizeof(host_path)) != 0) {
        return hrt_linux_failure(hrt_linux_errno(errno));
    }
    return hrt_host_result(readlink(host_path, buffer, size));
}

int64_t hrt_linux_fcntl(int fd, int command, uint64_t argument) {
    switch (command) {
        case 0: {
            int result = fcntl(fd, F_DUPFD, (int)argument);
            if (result >= 0) copy_fd_path(fd, result);
            return hrt_host_result(result);
        }
        case 1: return hrt_host_result(fcntl(fd, F_GETFD));
        case 2: return hrt_host_result(fcntl(fd, F_SETFD, (int)argument));
        case 3: return hrt_host_result(fcntl(fd, F_GETFL));
        case 4: return hrt_host_result(fcntl(
            fd, F_SETFL, hrt_translate_open_flags(argument)));
        case 1030: {
#ifdef F_DUPFD_CLOEXEC
            int result = fcntl(fd, F_DUPFD_CLOEXEC, (int)argument);
#else
            int result = fcntl(fd, F_DUPFD, (int)argument);
            if (result >= 0) (void)fcntl(result, F_SETFD, FD_CLOEXEC);
#endif
            if (result >= 0) copy_fd_path(fd, result);
            return hrt_host_result(result);
        }
        default: return hrt_linux_failure(HRT_LINUX_ENOSYS);
    }
}
