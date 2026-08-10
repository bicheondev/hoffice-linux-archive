#define _DARWIN_C_SOURCE 1
#include "hrt_m3.h"
#include "linux_abi.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <mach/i386/thread_status.h>
#include <mach/mach.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/ucontext.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif
#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

#define DARWIN_BSD_SYSCALL(number) (UINT64_C(0x02000000) + (number))
#define DARWIN_MACHDEP_SET_GS UINT64_C(0x03000003)
#define DARWIN_SYS_EXIT UINT64_C(1)
#define DARWIN_SYS_WRITE UINT64_C(4)
#define DARWIN_SYS_GETPID UINT64_C(20)

#define M3_BRK_RESERVE (UINT64_C(128) * 1024u * 1024u)
#define M3_UNKNOWN_LOG_LIMIT 128u

static volatile sig_atomic_t g_in_handler;
static volatile sig_atomic_t g_guest_tls_active;
static uintptr_t g_host_gs_base;
static uintptr_t g_guest_fs_base;
static char g_root[PATH_MAX];
static char g_guest_program[PATH_MAX];
static uintptr_t g_brk_base;
static uintptr_t g_brk_current;
static uintptr_t g_brk_end;
static uintptr_t g_clear_child_tid;
static unsigned int g_unknown_logs;

static inline int64_t raw_bsd_syscall0(uint64_t number) {
    uint64_t result;
    unsigned char failed;
    __asm__ volatile(
        "syscall\n\t"
        "setc %1"
        : "=a"(result), "=qm"(failed)
        : "0"(DARWIN_BSD_SYSCALL(number))
        : "rcx", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}

static inline int64_t raw_bsd_syscall3(uint64_t number,
                                       uint64_t argument1,
                                       uint64_t argument2,
                                       uint64_t argument3) {
    uint64_t result;
    unsigned char failed;
    __asm__ volatile(
        "syscall\n\t"
        "setc %1"
        : "=a"(result), "=qm"(failed)
        : "0"(DARWIN_BSD_SYSCALL(number)),
          "D"(argument1), "S"(argument2), "d"(argument3)
        : "rcx", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}

static inline uintptr_t raw_set_gs(uintptr_t base) {
    uintptr_t result;
    __asm__ volatile(
        "syscall"
        : "=a"(result)
        : "0"(DARWIN_MACHDEP_SET_GS), "D"(base)
        : "rcx", "r11", "cc", "memory");
    return result;
}

__attribute__((noreturn))
static void raw_exit(int status) {
    __asm__ volatile(
        "syscall"
        :
        : "a"(DARWIN_BSD_SYSCALL(DARWIN_SYS_EXIT)), "D"((uint64_t)status)
        : "rcx", "r11", "cc", "memory");
    __builtin_unreachable();
}

static void raw_write_literal(const char *message, size_t length) {
    (void)raw_bsd_syscall3(DARWIN_SYS_WRITE, STDERR_FILENO,
                           (uint64_t)(uintptr_t)message, length);
}

static void raw_log_unknown(uint64_t number) {
    if (g_unknown_logs >= M3_UNKNOWN_LOG_LIMIT) return;
    ++g_unknown_logs;

    char buffer[64];
    static const char prefix[] = "hrt-m3: Linux syscall ENOSYS ";
    size_t length = 0u;
    for (size_t index = 0u; index < sizeof(prefix) - 1u; ++index) {
        buffer[length++] = prefix[index];
    }
    char digits[24];
    size_t digit_count = 0u;
    do {
        digits[digit_count++] = (char)('0' + number % 10u);
        number /= 10u;
    } while (number != 0u && digit_count < sizeof(digits));
    while (digit_count != 0u) buffer[length++] = digits[--digit_count];
    buffer[length++] = '\n';
    raw_write_literal(buffer, length);
}

__attribute__((noreturn))
static void fail_from_signal(const char *message, size_t length, int status) {
    raw_write_literal(message, length);
    raw_exit(status);
}

static int linux_errno_from_host(int host_errno) {
    switch (host_errno) {
        case 0: return 0;
        case EPERM: return LINUX_EPERM;
        case ENOENT: return LINUX_ENOENT;
        case ESRCH: return LINUX_ESRCH;
        case EINTR: return LINUX_EINTR;
        case EIO: return LINUX_EIO;
        case EBADF: return LINUX_EBADF;
        case EAGAIN: return LINUX_EAGAIN;
        case ENOMEM: return LINUX_ENOMEM;
        case EACCES: return LINUX_EACCES;
        case EFAULT: return LINUX_EFAULT;
        case EBUSY: return LINUX_EBUSY;
        case EEXIST: return LINUX_EEXIST;
        case ENODEV: return LINUX_ENODEV;
        case ENOTDIR: return LINUX_ENOTDIR;
        case EISDIR: return LINUX_EISDIR;
        case EINVAL: return LINUX_EINVAL;
        case ENFILE: return LINUX_ENFILE;
        case EMFILE: return LINUX_EMFILE;
        case ENOTTY: return LINUX_ENOTTY;
        case EFBIG: return LINUX_EFBIG;
        case ENOSPC: return LINUX_ENOSPC;
        case ESPIPE: return LINUX_ESPIPE;
        case EROFS: return LINUX_EROFS;
        case EPIPE: return LINUX_EPIPE;
        case ERANGE: return LINUX_ERANGE;
        case ENOSYS: return LINUX_ENOSYS;
        case ENOTEMPTY: return LINUX_ENOTEMPTY;
        case ELOOP: return LINUX_ELOOP;
        case EOVERFLOW: return LINUX_EOVERFLOW;
        default: return LINUX_EIO;
    }
}

static int64_t linux_host_result(int64_t result, int host_errno) {
    return result < 0 ? -(int64_t)linux_errno_from_host(host_errno) : result;
}

static uintptr_t switch_to_host_context(void) {
    if (!g_guest_tls_active) return 0u;
    uintptr_t guest = g_guest_fs_base;
    (void)raw_set_gs(g_host_gs_base);
    return guest;
}

static void restore_guest_context(uintptr_t guest) {
    if (guest != 0u) (void)raw_set_gs(guest);
}

static int translate_guest_path(const char *guest_path,
                                char *host_path, size_t capacity) {
    if (guest_path == NULL || capacity == 0u) return -1;
    if (guest_path[0] != '/') {
        size_t length = strnlen(guest_path, capacity);
        if (length >= capacity) return -1;
        memcpy(host_path, guest_path, length + 1u);
        return 0;
    }

    size_t root_length = strlen(g_root);
    size_t path_length = strlen(guest_path);
    if (root_length + path_length + 1u > capacity) return -1;
    memcpy(host_path, g_root, root_length);
    memcpy(host_path + root_length, guest_path, path_length + 1u);
    return 0;
}

static int translate_open_flags(uint64_t linux_flags) {
    int host_flags;
    switch (linux_flags & LINUX_O_ACCMODE) {
        case LINUX_O_WRONLY: host_flags = O_WRONLY; break;
        case LINUX_O_RDWR: host_flags = O_RDWR; break;
        default: host_flags = O_RDONLY; break;
    }
    if ((linux_flags & LINUX_O_CREAT) != 0u) host_flags |= O_CREAT;
    if ((linux_flags & LINUX_O_EXCL) != 0u) host_flags |= O_EXCL;
    if ((linux_flags & LINUX_O_NOCTTY) != 0u) host_flags |= O_NOCTTY;
    if ((linux_flags & LINUX_O_TRUNC) != 0u) host_flags |= O_TRUNC;
    if ((linux_flags & LINUX_O_APPEND) != 0u) host_flags |= O_APPEND;
    if ((linux_flags & LINUX_O_NONBLOCK) != 0u) host_flags |= O_NONBLOCK;
#ifdef O_DIRECTORY
    if ((linux_flags & LINUX_O_DIRECTORY) != 0u) host_flags |= O_DIRECTORY;
#endif
#ifdef O_NOFOLLOW
    if ((linux_flags & LINUX_O_NOFOLLOW) != 0u) host_flags |= O_NOFOLLOW;
#endif
#ifdef O_CLOEXEC
    if ((linux_flags & LINUX_O_CLOEXEC) != 0u) host_flags |= O_CLOEXEC;
#endif
    return host_flags;
}

static int translate_protection(uint64_t linux_protection) {
    int protection = 0;
    if ((linux_protection & LINUX_PROT_READ) != 0u) protection |= PROT_READ;
    if ((linux_protection & LINUX_PROT_WRITE) != 0u) protection |= PROT_WRITE;
    if ((linux_protection & LINUX_PROT_EXEC) != 0u) protection |= PROT_EXEC;
    return protection;
}

static int translate_map_flags(uint64_t linux_flags) {
    int flags = 0;
    if ((linux_flags & LINUX_MAP_SHARED) != 0u) flags |= MAP_SHARED;
    if ((linux_flags & LINUX_MAP_PRIVATE) != 0u) flags |= MAP_PRIVATE;
    if ((linux_flags & LINUX_MAP_FIXED) != 0u) flags |= MAP_FIXED;
    if ((linux_flags & LINUX_MAP_ANONYMOUS) != 0u) flags |= MAP_ANONYMOUS;
#ifdef MAP_NORESERVE
    if ((linux_flags & LINUX_MAP_NORESERVE) != 0u) flags |= MAP_NORESERVE;
#endif
    return flags;
}

static void linux_stat_from_host(LinuxStat *guest, const struct stat *host) {
    memset(guest, 0, sizeof(*guest));
    guest->st_dev = (uint64_t)host->st_dev;
    guest->st_ino = (uint64_t)host->st_ino;
    guest->st_nlink = (uint64_t)host->st_nlink;
    guest->st_mode = (uint32_t)host->st_mode;
    guest->st_uid = (uint32_t)host->st_uid;
    guest->st_gid = (uint32_t)host->st_gid;
    guest->st_rdev = (uint64_t)host->st_rdev;
    guest->st_size = (int64_t)host->st_size;
    guest->st_blksize = (int64_t)host->st_blksize;
    guest->st_blocks = (int64_t)host->st_blocks;
    guest->st_atime_sec = (int64_t)host->st_atimespec.tv_sec;
    guest->st_atime_nsec = (int64_t)host->st_atimespec.tv_nsec;
    guest->st_mtime_sec = (int64_t)host->st_mtimespec.tv_sec;
    guest->st_mtime_nsec = (int64_t)host->st_mtimespec.tv_nsec;
    guest->st_ctime_sec = (int64_t)host->st_ctimespec.tv_sec;
    guest->st_ctime_nsec = (int64_t)host->st_ctimespec.tv_nsec;
}

static int64_t host_read_bridge(int fd, void *buffer, size_t size) {
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    ssize_t result = read(fd, buffer, size);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_write_bridge(int fd, const void *buffer, size_t size) {
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    ssize_t result = write(fd, buffer, size);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_close_bridge(int fd) {
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result = close(fd);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_open_bridge(int directory_fd, const char *guest_path,
                                uint64_t flags, uint64_t mode) {
    uintptr_t guest = switch_to_host_context();
    char path[PATH_MAX];
    if (translate_guest_path(guest_path, path, sizeof(path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    int host_flags = translate_open_flags(flags);
    errno = 0;
    int result;
    if (guest_path[0] == '/' || directory_fd == LINUX_AT_FDCWD) {
        result = open(path, host_flags, (mode_t)mode);
    } else {
        result = openat(directory_fd, path, host_flags, (mode_t)mode);
    }
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_pread_bridge(int fd, void *buffer, size_t size,
                                 int64_t offset) {
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    ssize_t result = pread(fd, buffer, size, (off_t)offset);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_lseek_bridge(int fd, int64_t offset, int whence) {
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    off_t result = lseek(fd, (off_t)offset, whence);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_fstat_bridge(int fd, LinuxStat *guest_stat) {
    if (guest_stat == NULL) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    struct stat host_stat;
    errno = 0;
    int result = fstat(fd, &host_stat);
    int saved_errno = errno;
    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_path_stat_bridge(const char *guest_path,
                                     LinuxStat *guest_stat, int follow) {
    if (guest_stat == NULL) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    char path[PATH_MAX];
    if (translate_guest_path(guest_path, path, sizeof(path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    struct stat host_stat;
    errno = 0;
    int result = follow ? stat(path, &host_stat) : lstat(path, &host_stat);
    int saved_errno = errno;
    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_fstatat_bridge(int directory_fd, const char *guest_path,
                                   LinuxStat *guest_stat, uint64_t flags) {
    if (guest_stat == NULL || guest_path == NULL) return -LINUX_EFAULT;
    if (guest_path[0] == '\0' && (flags & LINUX_AT_EMPTY_PATH) != 0u) {
        return host_fstat_bridge(directory_fd, guest_stat);
    }

    uintptr_t guest = switch_to_host_context();
    char path[PATH_MAX];
    if (translate_guest_path(guest_path, path, sizeof(path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    struct stat host_stat;
    int host_flags = 0;
#ifdef AT_SYMLINK_NOFOLLOW
    if ((flags & LINUX_AT_SYMLINK_NOFOLLOW) != 0u) {
        host_flags |= AT_SYMLINK_NOFOLLOW;
    }
#endif
    errno = 0;
    int result;
    if (guest_path[0] == '/' || directory_fd == LINUX_AT_FDCWD) {
        result = (host_flags != 0) ? lstat(path, &host_stat)
                                   : stat(path, &host_stat);
    } else {
        result = fstatat(directory_fd, path, &host_stat, host_flags);
    }
    int saved_errno = errno;
    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_access_bridge(int directory_fd, const char *guest_path,
                                  int mode, uint64_t flags) {
    uintptr_t guest = switch_to_host_context();
    char path[PATH_MAX];
    if (translate_guest_path(guest_path, path, sizeof(path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    errno = 0;
    int result;
    if (guest_path[0] == '/' || directory_fd == LINUX_AT_FDCWD) {
        result = access(path, mode);
    } else {
        int host_flags = 0;
#ifdef AT_EACCESS
        if ((flags & 0x200u) != 0u) host_flags |= AT_EACCESS;
#endif
        result = faccessat(directory_fd, path, mode, host_flags);
    }
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_readlink_bridge(const char *guest_path,
                                    char *buffer, size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (strcmp(guest_path, "/proc/self/exe") == 0) {
        size_t length = strlen(g_guest_program);
        if (length > size) length = size;
        memcpy(buffer, g_guest_program, length);
        return (int64_t)length;
    }

    uintptr_t guest = switch_to_host_context();
    char path[PATH_MAX];
    if (translate_guest_path(guest_path, path, sizeof(path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    errno = 0;
    ssize_t result = readlink(path, buffer, size);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_mmap_bridge(uintptr_t address, size_t length,
                                uint64_t linux_protection,
                                uint64_t linux_flags, int fd,
                                uint64_t offset) {
    int protection = translate_protection(linux_protection);
    int map_flags = translate_map_flags(linux_flags);
    int needs_exec_patch = (protection & PROT_EXEC) != 0;
    int temporary_protection = protection |
        (needs_exec_patch ? PROT_WRITE : 0);
    int fixed_noreplace =
        (linux_flags & LINUX_MAP_FIXED_NOREPLACE) != 0u;

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    void *result = mmap((void *)address, length, temporary_protection,
                        map_flags, fd, (off_t)offset);
    int saved_errno = errno;
    if (result != MAP_FAILED && fixed_noreplace &&
        (uintptr_t)result != address) {
        (void)munmap(result, length);
        restore_guest_context(guest);
        return -LINUX_EEXIST;
    }
    if (result != MAP_FAILED && needs_exec_patch) {
        size_t rewritten_fs = 0u;
        (void)patch_guest_code(result, length, &rewritten_fs);
        if (mprotect(result, length, protection) != 0) {
            saved_errno = errno;
            (void)munmap(result, length);
            result = MAP_FAILED;
        }
    }
    restore_guest_context(guest);
    if (result == MAP_FAILED) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }
    return (int64_t)(uintptr_t)result;
}

static int64_t host_mprotect_bridge(void *address, size_t length,
                                    uint64_t linux_protection) {
    int protection = translate_protection(linux_protection);
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result;
    if ((protection & PROT_EXEC) != 0) {
        result = mprotect(address, length,
                          protection | PROT_READ | PROT_WRITE);
        if (result == 0) {
            size_t rewritten_fs = 0u;
            (void)patch_guest_code(address, length, &rewritten_fs);
            result = mprotect(address, length, protection);
        }
    } else {
        result = mprotect(address, length, protection);
    }
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_munmap_bridge(void *address, size_t length) {
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result = munmap(address, length);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_madvise_bridge(void *address, size_t length, int advice) {
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result = madvise(address, length, advice);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static uint64_t bridge_brk(uintptr_t requested) {
    if (requested == 0u) return (uint64_t)g_brk_current;
    if (requested < g_brk_base || requested > g_brk_end) {
        return (uint64_t)g_brk_current;
    }

    uintptr_t old_page = align_up(g_brk_current, g_page_size);
    uintptr_t new_page = align_up(requested, g_page_size);
    uintptr_t guest = switch_to_host_context();
    int result = 0;
    if (new_page > old_page) {
        result = mprotect((void *)old_page, new_page - old_page,
                          PROT_READ | PROT_WRITE);
    } else if (new_page < old_page) {
        result = mprotect((void *)new_page, old_page - new_page, PROT_NONE);
    }
    restore_guest_context(guest);
    if (result == 0) g_brk_current = requested;
    return (uint64_t)g_brk_current;
}

static int64_t host_fcntl_bridge(int fd, int command, uint64_t argument) {
    int host_command;
    switch (command) {
        case LINUX_F_GETFD: host_command = F_GETFD; break;
        case LINUX_F_SETFD: host_command = F_SETFD; break;
        case LINUX_F_GETFL: host_command = F_GETFL; break;
        case LINUX_F_SETFL: host_command = F_SETFL; break;
        default: return -LINUX_EINVAL;
    }
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result = fcntl(fd, host_command, (long)argument);
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t bridge_clock_gettime(int clock_id,
                                    LinuxTimespec *guest_time) {
    if (guest_time == NULL) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    struct timespec host_time;
    errno = 0;
    int result = clock_gettime((clockid_t)clock_id, &host_time);
    int saved_errno = errno;
    if (result == 0) {
        guest_time->tv_sec = (int64_t)host_time.tv_sec;
        guest_time->tv_nsec = (int64_t)host_time.tv_nsec;
    }
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t bridge_gettimeofday(LinuxTimeval *guest_time) {
    if (guest_time == NULL) return 0;
    uintptr_t guest = switch_to_host_context();
    struct timeval host_time;
    errno = 0;
    int result = gettimeofday(&host_time, NULL);
    int saved_errno = errno;
    if (result == 0) {
        guest_time->tv_sec = (int64_t)host_time.tv_sec;
        guest_time->tv_usec = (int64_t)host_time.tv_usec;
    }
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t bridge_getrandom(void *buffer, size_t size) {
    if (buffer == NULL && size != 0u) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    arc4random_buf(buffer, size);
    restore_guest_context(guest);
    return (int64_t)size;
}

static int64_t bridge_uname(LinuxUtsname *name) {
    if (name == NULL) return -LINUX_EFAULT;
    memset(name, 0, sizeof(*name));
    memcpy(name->sysname, "Linux", 6u);
    memcpy(name->nodename, "hoffice-macos", 14u);
    memcpy(name->release, "5.10.0-hrt", 11u);
    memcpy(name->version, "HOffice Runtime M3", 19u);
    memcpy(name->machine, "x86_64", 7u);
    memcpy(name->domainname, "localdomain", 12u);
    return 0;
}

static int64_t bridge_getcwd(char *buffer, size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (size < 2u) return -LINUX_ERANGE;
    buffer[0] = '/';
    buffer[1] = '\0';
    return 2;
}

static int64_t bridge_getrlimit(uint64_t resource, LinuxRlimit *limit) {
    if (limit == NULL) return -LINUX_EFAULT;
    if (resource == LINUX_RLIMIT_STACK) {
        limit->rlim_cur = HRT_STACK_SIZE;
        limit->rlim_max = UINT64_MAX;
    } else {
        limit->rlim_cur = UINT64_MAX;
        limit->rlim_max = UINT64_MAX;
    }
    return 0;
}

static int64_t bridge_prlimit64(uint64_t resource,
                                const LinuxRlimit *new_limit,
                                LinuxRlimit *old_limit) {
    (void)new_limit;
    if (old_limit != NULL) return bridge_getrlimit(resource, old_limit);
    return 0;
}

static int64_t bridge_futex(uint32_t *address, uint32_t operation,
                            uint32_t expected) {
    if (address == NULL) return -LINUX_EFAULT;
    uint32_t command = operation & LINUX_FUTEX_CMD_MASK;
    if (command == LINUX_FUTEX_WAKE) return 0;
    if (command == LINUX_FUTEX_WAIT) {
        return *address == expected ? -LINUX_EAGAIN : -LINUX_EAGAIN;
    }
    return -LINUX_ENOSYS;
}

static void sigill_handler(int signo, siginfo_t *info, void *context_pointer) {
    (void)signo;
    (void)info;
    if (g_in_handler) raw_exit(125);
    g_in_handler = 1;

#if defined(__x86_64__)
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uint64_t rip = state->__rip;
    const unsigned char *instruction =
        (const unsigned char *)(uintptr_t)rip;
    if (instruction[0] != 0x0fu || instruction[1] != 0x0bu) {
        static const char message[] = "hrt-m3: unexpected SIGILL\n";
        fail_from_signal(message, sizeof(message) - 1u, 124);
    }

    int64_t result;
    switch (state->__rax) {
        case LINUX_SYS_READ:
            result = host_read_bridge((int)state->__rdi,
                                      (void *)(uintptr_t)state->__rsi,
                                      (size_t)state->__rdx);
            break;
        case LINUX_SYS_WRITE:
            result = host_write_bridge((int)state->__rdi,
                                       (const void *)(uintptr_t)state->__rsi,
                                       (size_t)state->__rdx);
            break;
        case LINUX_SYS_OPEN:
            result = host_open_bridge(LINUX_AT_FDCWD,
                                      (const char *)(uintptr_t)state->__rdi,
                                      state->__rsi, state->__rdx);
            break;
        case LINUX_SYS_CLOSE:
            result = host_close_bridge((int)state->__rdi);
            break;
        case LINUX_SYS_STAT:
            result = host_path_stat_bridge(
                (const char *)(uintptr_t)state->__rdi,
                (LinuxStat *)(uintptr_t)state->__rsi, 1);
            break;
        case LINUX_SYS_FSTAT:
            result = host_fstat_bridge(
                (int)state->__rdi,
                (LinuxStat *)(uintptr_t)state->__rsi);
            break;
        case LINUX_SYS_LSTAT:
            result = host_path_stat_bridge(
                (const char *)(uintptr_t)state->__rdi,
                (LinuxStat *)(uintptr_t)state->__rsi, 0);
            break;
        case LINUX_SYS_LSEEK:
            result = host_lseek_bridge((int)state->__rdi,
                                       (int64_t)state->__rsi,
                                       (int)state->__rdx);
            break;
        case LINUX_SYS_MMAP:
            result = host_mmap_bridge(
                (uintptr_t)state->__rdi, (size_t)state->__rsi,
                state->__rdx, state->__r10, (int)state->__r8,
                state->__r9);
            break;
        case LINUX_SYS_MPROTECT:
            result = host_mprotect_bridge(
                (void *)(uintptr_t)state->__rdi,
                (size_t)state->__rsi, state->__rdx);
            break;
        case LINUX_SYS_MUNMAP:
            result = host_munmap_bridge(
                (void *)(uintptr_t)state->__rdi,
                (size_t)state->__rsi);
            break;
        case LINUX_SYS_BRK:
            result = (int64_t)bridge_brk((uintptr_t)state->__rdi);
            break;
        case LINUX_SYS_RT_SIGACTION:
            if (state->__rdx != 0u) {
                memset((void *)(uintptr_t)state->__rdx, 0,
                       (size_t)(state->__r10 < 32u ? state->__r10 : 32u));
            }
            result = 0;
            break;
        case LINUX_SYS_RT_SIGPROCMASK:
            if (state->__rdx != 0u) {
                memset((void *)(uintptr_t)state->__rdx, 0,
                       (size_t)state->__r10);
            }
            result = 0;
            break;
        case LINUX_SYS_IOCTL:
            result = -LINUX_ENOTTY;
            break;
        case LINUX_SYS_PREAD64:
            result = host_pread_bridge(
                (int)state->__rdi, (void *)(uintptr_t)state->__rsi,
                (size_t)state->__rdx, (int64_t)state->__r10);
            break;
        case LINUX_SYS_ACCESS:
            result = host_access_bridge(
                LINUX_AT_FDCWD, (const char *)(uintptr_t)state->__rdi,
                (int)state->__rsi, 0u);
            break;
        case LINUX_SYS_MADVISE:
            result = host_madvise_bridge(
                (void *)(uintptr_t)state->__rdi,
                (size_t)state->__rsi, (int)state->__rdx);
            break;
        case LINUX_SYS_GETPID:
            result = raw_bsd_syscall0(DARWIN_SYS_GETPID);
            break;
        case LINUX_SYS_EXIT:
        case LINUX_SYS_EXIT_GROUP:
            raw_exit((int)(state->__rdi & 0xffu));
        case LINUX_SYS_UNAME:
            result = bridge_uname((LinuxUtsname *)(uintptr_t)state->__rdi);
            break;
        case LINUX_SYS_FCNTL:
            result = host_fcntl_bridge((int)state->__rdi,
                                       (int)state->__rsi,
                                       state->__rdx);
            break;
        case LINUX_SYS_GETCWD:
            result = bridge_getcwd((char *)(uintptr_t)state->__rdi,
                                   (size_t)state->__rsi);
            break;
        case LINUX_SYS_READLINK:
            result = host_readlink_bridge(
                (const char *)(uintptr_t)state->__rdi,
                (char *)(uintptr_t)state->__rsi,
                (size_t)state->__rdx);
            break;
        case LINUX_SYS_GETTIMEOFDAY:
            result = bridge_gettimeofday(
                (LinuxTimeval *)(uintptr_t)state->__rdi);
            break;
        case LINUX_SYS_GETRLIMIT:
            result = bridge_getrlimit(
                state->__rdi, (LinuxRlimit *)(uintptr_t)state->__rsi);
            break;
        case LINUX_SYS_GETUID:
            result = (int64_t)getuid();
            break;
        case LINUX_SYS_GETGID:
            result = (int64_t)getgid();
            break;
        case LINUX_SYS_GETEUID:
            result = (int64_t)geteuid();
            break;
        case LINUX_SYS_GETEGID:
            result = (int64_t)getegid();
            break;
        case LINUX_SYS_ARCH_PRCTL:
            if (state->__rdi == LINUX_ARCH_SET_FS) {
                g_guest_fs_base = (uintptr_t)state->__rsi;
                g_guest_tls_active = 1;
                (void)raw_set_gs(g_guest_fs_base);
                result = 0;
            } else if (state->__rdi == LINUX_ARCH_GET_FS) {
                if (state->__rsi == 0u) {
                    result = -LINUX_EFAULT;
                } else {
                    *(uint64_t *)(uintptr_t)state->__rsi =
                        (uint64_t)g_guest_fs_base;
                    result = 0;
                }
            } else {
                result = -LINUX_EINVAL;
            }
            break;
        case LINUX_SYS_GETTID:
            result = raw_bsd_syscall0(DARWIN_SYS_GETPID);
            break;
        case LINUX_SYS_FUTEX:
            result = bridge_futex((uint32_t *)(uintptr_t)state->__rdi,
                                  (uint32_t)state->__rsi,
                                  (uint32_t)state->__rdx);
            break;
        case LINUX_SYS_SET_TID_ADDRESS:
            g_clear_child_tid = (uintptr_t)state->__rdi;
            result = raw_bsd_syscall0(DARWIN_SYS_GETPID);
            break;
        case LINUX_SYS_CLOCK_GETTIME:
            result = bridge_clock_gettime(
                (int)state->__rdi,
                (LinuxTimespec *)(uintptr_t)state->__rsi);
            break;
        case LINUX_SYS_OPENAT:
            result = host_open_bridge(
                (int)state->__rdi,
                (const char *)(uintptr_t)state->__rsi,
                state->__rdx, state->__r10);
            break;
        case LINUX_SYS_NEWFSTATAT:
            result = host_fstatat_bridge(
                (int)state->__rdi,
                (const char *)(uintptr_t)state->__rsi,
                (LinuxStat *)(uintptr_t)state->__rdx,
                state->__r10);
            break;
        case LINUX_SYS_SET_ROBUST_LIST:
            result = 0;
            break;
        case LINUX_SYS_PRLIMIT64:
            result = bridge_prlimit64(
                state->__rsi,
                (const LinuxRlimit *)(uintptr_t)state->__rdx,
                (LinuxRlimit *)(uintptr_t)state->__r10);
            break;
        case LINUX_SYS_GETRANDOM:
            result = bridge_getrandom(
                (void *)(uintptr_t)state->__rdi,
                (size_t)state->__rsi);
            break;
        case LINUX_SYS_FACCESSAT2:
            result = host_access_bridge(
                (int)state->__rdi,
                (const char *)(uintptr_t)state->__rsi,
                (int)state->__rdx, state->__r10);
            break;
        case LINUX_SYS_RSEQ:
        case LINUX_SYS_STATX:
        case LINUX_SYS_CLONE3:
            result = -LINUX_ENOSYS;
            break;
        default:
            raw_log_unknown(state->__rax);
            result = -LINUX_ENOSYS;
            break;
    }

    state->__rax = (uint64_t)result;
    state->__rip = rip + 2u;
    g_in_handler = 0;
#else
#error "hrt-m3 must be built as x86_64 Mach-O"
#endif
}

static uintptr_t capture_host_gs_base(void) {
    x86_thread_full_state64_t state;
    mach_msg_type_number_t count = x86_THREAD_FULL_STATE64_COUNT;
    memset(&state, 0, sizeof(state));
    mach_port_t thread = mach_thread_self();
    kern_return_t result = thread_get_state(
        thread, x86_THREAD_FULL_STATE64,
        (thread_state_t)&state, &count);
    (void)mach_port_deallocate(mach_task_self(), thread);
    if (result == KERN_SUCCESS && state.__gsbase != 0u) {
        return (uintptr_t)state.__gsbase;
    }
    return (uintptr_t)pthread_self();
}

void initialize_syscall_bridge(const char *root,
                               const char *guest_program) {
    if (strlcpy(g_root, root, sizeof(g_root)) >= sizeof(g_root) ||
        strlcpy(g_guest_program, guest_program,
                sizeof(g_guest_program)) >= sizeof(g_guest_program)) {
        errno = 0;
        fatal("M3 root or guest path is too long");
    }
    g_host_gs_base = capture_host_gs_base();
    if (g_host_gs_base == 0u) {
        errno = 0;
        fatal("could not capture host GS base");
    }

    void *brk_reserve = mmap(NULL, (size_t)M3_BRK_RESERVE, PROT_NONE,
                             MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (brk_reserve == MAP_FAILED) fatal("reserve M3 brk arena");
    g_brk_base = (uintptr_t)brk_reserve;
    g_brk_current = g_brk_base;
    g_brk_end = g_brk_base + (uintptr_t)M3_BRK_RESERVE;

    if (chdir(root) != 0) fatal("chdir M3 rootfs");

    void *altstack = mmap(NULL, HRT_ALTSTACK_SIZE,
                          PROT_READ | PROT_WRITE,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (altstack == MAP_FAILED) fatal("mmap M3 alternate signal stack");
    stack_t stack;
    memset(&stack, 0, sizeof(stack));
    stack.ss_sp = altstack;
    stack.ss_size = HRT_ALTSTACK_SIZE;
    if (sigaltstack(&stack, NULL) != 0) fatal("M3 sigaltstack");

    struct sigaction action;
    memset(&action, 0, sizeof(action));
    sigemptyset(&action.sa_mask);
    action.sa_sigaction = sigill_handler;
    action.sa_flags = SA_SIGINFO | SA_ONSTACK;
    if (sigaction(SIGILL, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGILL)");
    }
}
