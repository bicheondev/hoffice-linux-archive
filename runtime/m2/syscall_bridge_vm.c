#define _DARWIN_C_SOURCE 1
#include "glibc_host.h"
#include "vm_compat.h"

#include <errno.h>
#include <fcntl.h>
#include <mach/i386/thread_status.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/ucontext.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

_Static_assert(sizeof(struct linux_stat64) == 144u,
               "Linux x86-64 stat ABI size changed");
_Static_assert(sizeof(struct linux_sysinfo64) == 112u,
               "Linux x86-64 sysinfo ABI size changed");

static volatile sig_atomic_t g_in_bridge;
static uintptr_t g_brk_base;
static uintptr_t g_brk_current;
static uintptr_t g_brk_limit;
static struct linux_kernel_sigaction g_guest_sigactions[65];
static uint64_t g_guest_signal_mask;
static struct linux_stack64 g_guest_altstack;
static char g_guest_process_name[16] = "hrt-m2";

static uintptr_t read_fs_base(void) {
    uintptr_t value;
    __asm__ volatile("rdfsbase %0" : "=r"(value));
    return value;
}

static void write_fs_base(uintptr_t value) {
    __asm__ volatile("wrfsbase %0" : : "r"(value) : "memory");
}

static void bridge_die_literal(const char *message, size_t size, int status)
    __attribute__((noreturn));

static void bridge_die_literal(const char *message, size_t size, int status) {
    (void)write(STDERR_FILENO, message, size);
    _exit(status);
}

static void bridge_die_syscall(uint64_t number) __attribute__((noreturn));

static void bridge_die_syscall(uint64_t number) {
    char buffer[96];
    static const char prefix[] = "hrt-m2: unsupported Linux syscall ";
    size_t cursor = 0;
    memcpy(buffer + cursor, prefix, sizeof(prefix) - 1u);
    cursor += sizeof(prefix) - 1u;

    char digits[24];
    size_t count = 0;
    do {
        digits[count++] = (char)('0' + (number % 10u));
        number /= 10u;
    } while (number != 0u && count < sizeof(digits));
    while (count != 0u) buffer[cursor++] = digits[--count];
    buffer[cursor++] = '\n';
    bridge_die_literal(buffer, cursor, 126);
}

static int path_has_parent_component(const char *path) {
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

static long copy_guest_path(uint64_t guest_pointer, char output[PATH_MAX]) {
    if (guest_pointer == 0u) return -LINUX_EFAULT;
    const char *source = (const char *)(uintptr_t)guest_pointer;
    for (size_t index = 0; index < (size_t)PATH_MAX; ++index) {
        output[index] = source[index];
        if (source[index] == '\0') {
            if (path_has_parent_component(output)) return -LINUX_EACCES;
            return 0;
        }
    }
    output[PATH_MAX - 1] = '\0';
    return -LINUX_ENAMETOOLONG;
}

static const char *relative_to_virtual_root(const char *path) {
    while (*path == '/') ++path;
    return *path == '\0' ? "." : path;
}

static int host_dirfd_for(int linux_dirfd, const char *path) {
    if (path[0] == '/' || linux_dirfd == LINUX_AT_FDCWD) return g_sysroot_fd;
    return linux_dirfd;
}

static const char *host_path_for(const char *path) {
    return path[0] == '/' ? relative_to_virtual_root(path) : path;
}

static int translate_open_flags(uint64_t linux_flags) {
    int host_flags;
    switch ((int)(linux_flags & LINUX_O_ACCMODE)) {
        case LINUX_O_WRONLY: host_flags = O_WRONLY; break;
        case LINUX_O_RDWR: host_flags = O_RDWR; break;
        default: host_flags = O_RDONLY; break;
    }
    if ((linux_flags & LINUX_O_CREAT) != 0u) host_flags |= O_CREAT;
    if ((linux_flags & LINUX_O_EXCL) != 0u) host_flags |= O_EXCL;
#ifdef O_NOCTTY
    if ((linux_flags & LINUX_O_NOCTTY) != 0u) host_flags |= O_NOCTTY;
#endif
    if ((linux_flags & LINUX_O_TRUNC) != 0u) host_flags |= O_TRUNC;
    if ((linux_flags & LINUX_O_APPEND) != 0u) host_flags |= O_APPEND;
    if ((linux_flags & LINUX_O_NONBLOCK) != 0u) host_flags |= O_NONBLOCK;
#ifdef O_DSYNC
    if ((linux_flags & LINUX_O_DSYNC) != 0u) host_flags |= O_DSYNC;
#endif
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

static long guest_openat(int linux_dirfd, uint64_t guest_path,
                         uint64_t linux_flags, uint64_t mode) {
    char path[PATH_MAX];
    long copied = copy_guest_path(guest_path, path);
    if (copied != 0) return copied;
    int result = openat(host_dirfd_for(linux_dirfd, path),
                        host_path_for(path),
                        translate_open_flags(linux_flags),
                        (mode_t)mode);
    return hrt_linux_result((long)result);
}

static void convert_stat(const struct stat *host,
                         struct linux_stat64 *output) {
    memset(output, 0, sizeof(*output));
    output->dev = (uint64_t)host->st_dev;
    output->ino = (uint64_t)host->st_ino;
    output->nlink = (uint64_t)host->st_nlink;
    output->mode = (uint32_t)host->st_mode;
    output->uid = (uint32_t)host->st_uid;
    output->gid = (uint32_t)host->st_gid;
    output->rdev = (uint64_t)host->st_rdev;
    output->size = (int64_t)host->st_size;
    output->blksize = (int64_t)host->st_blksize;
    output->blocks = (int64_t)host->st_blocks;
    output->atime_sec = (int64_t)host->st_atimespec.tv_sec;
    output->atime_nsec = (int64_t)host->st_atimespec.tv_nsec;
    output->mtime_sec = (int64_t)host->st_mtimespec.tv_sec;
    output->mtime_nsec = (int64_t)host->st_mtimespec.tv_nsec;
    output->ctime_sec = (int64_t)host->st_ctimespec.tv_sec;
    output->ctime_nsec = (int64_t)host->st_ctimespec.tv_nsec;
}

static long guest_fstat(int fd, uint64_t output_pointer) {
    if (output_pointer == 0u) return -LINUX_EFAULT;
    struct stat host;
    if (fstat(fd, &host) != 0) return hrt_linux_result(-1);
    convert_stat(&host, (struct linux_stat64 *)(uintptr_t)output_pointer);
    return 0;
}

static long guest_fstatat(int linux_dirfd, uint64_t guest_path,
                          uint64_t output_pointer, uint64_t linux_flags) {
    if (output_pointer == 0u) return -LINUX_EFAULT;
    char path[PATH_MAX];
    long copied = copy_guest_path(guest_path, path);
    if (copied != 0) return copied;

    struct stat host;
    if (path[0] == '\0' &&
        (linux_flags & LINUX_AT_EMPTY_PATH) != 0u &&
        linux_dirfd != LINUX_AT_FDCWD) {
        if (fstat(linux_dirfd, &host) != 0) return hrt_linux_result(-1);
    } else {
        int flags = 0;
#ifdef AT_SYMLINK_NOFOLLOW
        if ((linux_flags & LINUX_AT_SYMLINK_NOFOLLOW) != 0u) {
            flags |= AT_SYMLINK_NOFOLLOW;
        }
#endif
        if (fstatat(host_dirfd_for(linux_dirfd, path),
                    host_path_for(path), &host, flags) != 0) {
            return hrt_linux_result(-1);
        }
    }
    convert_stat(&host, (struct linux_stat64 *)(uintptr_t)output_pointer);
    return 0;
}

static long guest_accessat(int linux_dirfd, uint64_t guest_path, int mode) {
    char path[PATH_MAX];
    long copied = copy_guest_path(guest_path, path);
    if (copied != 0) return copied;
    return hrt_linux_result((long)faccessat(
        host_dirfd_for(linux_dirfd, path), host_path_for(path), mode, 0));
}

static long guest_readlinkat(int linux_dirfd, uint64_t guest_path,
                             uint64_t buffer_pointer, size_t buffer_size) {
    if (buffer_pointer == 0u) return -LINUX_EFAULT;
    char path[PATH_MAX];
    long copied = copy_guest_path(guest_path, path);
    if (copied != 0) return copied;
    char *buffer = (char *)(uintptr_t)buffer_pointer;

    if (strcmp(path, "/proc/self/exe") == 0) {
        size_t length = strlen(g_guest_program);
        if (length > buffer_size) length = buffer_size;
        memcpy(buffer, g_guest_program, length);
        return (long)length;
    }
    ssize_t result = readlinkat(host_dirfd_for(linux_dirfd, path),
                                host_path_for(path), buffer, buffer_size);
    return hrt_linux_result((long)result);
}

static long guest_getrandom(uint64_t buffer_pointer, size_t length) {
    if (buffer_pointer == 0u && length != 0u) return -LINUX_EFAULT;
    unsigned char *cursor = (unsigned char *)(uintptr_t)buffer_pointer;
    size_t remaining = length;
    while (remaining != 0u) {
        size_t chunk = remaining > 256u ? 256u : remaining;
        if (getentropy(cursor, chunk) != 0) return hrt_linux_result(-1);
        cursor += chunk;
        remaining -= chunk;
    }
    return (long)length;
}

static int host_clock_id(int linux_clock) {
    switch (linux_clock) {
        case 0: return CLOCK_REALTIME;
        case 1: return CLOCK_MONOTONIC;
#ifdef CLOCK_PROCESS_CPUTIME_ID
        case 2: return CLOCK_PROCESS_CPUTIME_ID;
#endif
#ifdef CLOCK_THREAD_CPUTIME_ID
        case 3: return CLOCK_THREAD_CPUTIME_ID;
#endif
        default: return -1;
    }
}

static long guest_clock_gettime(int linux_clock, uint64_t output_pointer) {
    if (output_pointer == 0u) return -LINUX_EFAULT;
    int clock = host_clock_id(linux_clock);
    if (clock < 0) return -LINUX_EINVAL;
    struct timespec value;
    if (clock_gettime((clockid_t)clock, &value) != 0) {
        return hrt_linux_result(-1);
    }
    struct linux_timespec64 *output =
        (struct linux_timespec64 *)(uintptr_t)output_pointer;
    output->tv_sec = (int64_t)value.tv_sec;
    output->tv_nsec = (int64_t)value.tv_nsec;
    return 0;
}

static long guest_clock_getres(int linux_clock, uint64_t output_pointer) {
    int clock = host_clock_id(linux_clock);
    if (clock < 0) return -LINUX_EINVAL;
    if (output_pointer == 0u) return 0;
    struct timespec value;
    if (clock_getres((clockid_t)clock, &value) != 0) {
        return hrt_linux_result(-1);
    }
    struct linux_timespec64 *output =
        (struct linux_timespec64 *)(uintptr_t)output_pointer;
    output->tv_sec = (int64_t)value.tv_sec;
    output->tv_nsec = (int64_t)value.tv_nsec;
    return 0;
}

static long guest_nanosleep(uint64_t request_pointer,
                            uint64_t remainder_pointer) {
    if (request_pointer == 0u) return -LINUX_EFAULT;
    const struct linux_timespec64 *request =
        (const struct linux_timespec64 *)(uintptr_t)request_pointer;
    struct timespec host_request = {
        .tv_sec = (time_t)request->tv_sec,
        .tv_nsec = (long)request->tv_nsec,
    };
    struct timespec host_remainder;
    int result = nanosleep(&host_request,
                           remainder_pointer == 0u ? NULL : &host_remainder);
    if (result != 0 && remainder_pointer != 0u) {
        struct linux_timespec64 *remainder =
            (struct linux_timespec64 *)(uintptr_t)remainder_pointer;
        remainder->tv_sec = (int64_t)host_remainder.tv_sec;
        remainder->tv_nsec = (int64_t)host_remainder.tv_nsec;
    }
    return hrt_linux_result((long)result);
}

static long guest_futex(uint64_t address, uint32_t operation,
                        uint32_t expected, uint64_t timeout_pointer) {
    if (address == 0u) return -LINUX_EFAULT;
    uint32_t command = operation & LINUX_FUTEX_CMD_MASK;
    volatile uint32_t *word = (volatile uint32_t *)(uintptr_t)address;
    if (command == LINUX_FUTEX_WAKE ||
        command == LINUX_FUTEX_WAKE_BITSET) {
        return 0;
    }
    if (command == LINUX_FUTEX_WAIT ||
        command == LINUX_FUTEX_WAIT_BITSET) {
        if (*word != expected) return -LINUX_EAGAIN;
        if (timeout_pointer != 0u) {
            (void)guest_nanosleep(timeout_pointer, 0);
            return -LINUX_ETIMEDOUT;
        }
        return -LINUX_EAGAIN;
    }
    return -LINUX_ENOSYS;
}

static long guest_prlimit(int resource, uint64_t new_limit_pointer,
                          uint64_t old_limit_pointer) {
    if (new_limit_pointer != 0u) return -LINUX_EPERM;
    if (old_limit_pointer == 0u) return 0;
    struct linux_rlimit64 *limit =
        (struct linux_rlimit64 *)(uintptr_t)old_limit_pointer;
    if (resource == LINUX_RLIMIT_STACK) {
        limit->current = HRT_M2_STACK_SIZE;
        limit->maximum = LINUX_RLIM_INFINITY;
    } else if (resource == LINUX_RLIMIT_NOFILE) {
        limit->current = 1024;
        limit->maximum = 1024;
    } else {
        limit->current = LINUX_RLIM_INFINITY;
        limit->maximum = LINUX_RLIM_INFINITY;
    }
    return 0;
}

static long guest_uname(uint64_t output_pointer) {
    if (output_pointer == 0u) return -LINUX_EFAULT;
    struct linux_utsname *name =
        (struct linux_utsname *)(uintptr_t)output_pointer;
    memset(name, 0, sizeof(*name));
    (void)snprintf(name->sysname, sizeof(name->sysname), "Linux");
    (void)snprintf(name->nodename, sizeof(name->nodename), "hrt-macos");
    (void)snprintf(name->release, sizeof(name->release), "5.10.0-hrt");
    (void)snprintf(name->version, sizeof(name->version), "#1 HRT M2");
    (void)snprintf(name->machine, sizeof(name->machine), "x86_64");
    return 0;
}

static long guest_pipe2(uint64_t output_pointer, uint64_t linux_flags) {
    if (output_pointer == 0u) return -LINUX_EFAULT;
    int descriptors[2];
    if (pipe(descriptors) != 0) return hrt_linux_result(-1);
    for (size_t index = 0; index < 2u; ++index) {
        if ((linux_flags & LINUX_O_CLOEXEC) != 0u) {
            (void)fcntl(descriptors[index], F_SETFD, FD_CLOEXEC);
        }
        if ((linux_flags & LINUX_O_NONBLOCK) != 0u) {
            int current = fcntl(descriptors[index], F_GETFL);
            if (current >= 0) {
                (void)fcntl(descriptors[index], F_SETFL,
                            current | O_NONBLOCK);
            }
        }
    }
    int32_t *output = (int32_t *)(uintptr_t)output_pointer;
    output[0] = descriptors[0];
    output[1] = descriptors[1];
    return 0;
}

static long guest_rt_sigaction(int signal_number, uint64_t action_pointer,
                               uint64_t old_pointer, size_t mask_size) {
    if (signal_number <= 0 || signal_number >= 65 || mask_size != 8u) {
        return -LINUX_EINVAL;
    }
    if (old_pointer != 0u) {
        memcpy((void *)(uintptr_t)old_pointer,
               &g_guest_sigactions[signal_number],
               sizeof(struct linux_kernel_sigaction));
    }
    if (action_pointer != 0u) {
        memcpy(&g_guest_sigactions[signal_number],
               (const void *)(uintptr_t)action_pointer,
               sizeof(struct linux_kernel_sigaction));
    }
    return 0;
}

static long guest_rt_sigprocmask(int how, uint64_t set_pointer,
                                 uint64_t old_pointer, size_t mask_size) {
    if (mask_size != 8u) return -LINUX_EINVAL;
    if (old_pointer != 0u) {
        *(uint64_t *)(uintptr_t)old_pointer = g_guest_signal_mask;
    }
    if (set_pointer != 0u) {
        uint64_t requested = *(const uint64_t *)(uintptr_t)set_pointer;
        if (how == 0) g_guest_signal_mask |= requested;
        else if (how == 1) g_guest_signal_mask &= ~requested;
        else if (how == 2) g_guest_signal_mask = requested;
        else return -LINUX_EINVAL;
    }
    return 0;
}

static long guest_sigaltstack(uint64_t new_pointer, uint64_t old_pointer) {
    if (old_pointer != 0u) {
        memcpy((void *)(uintptr_t)old_pointer,
               &g_guest_altstack, sizeof(g_guest_altstack));
    }
    if (new_pointer != 0u) {
        memcpy(&g_guest_altstack,
               (const void *)(uintptr_t)new_pointer,
               sizeof(g_guest_altstack));
    }
    return 0;
}

static long guest_arch_prctl(uint64_t code, uint64_t address) {
    switch (code) {
        case LINUX_ARCH_SET_FS:
            write_fs_base((uintptr_t)address);
            return 0;
        case LINUX_ARCH_GET_FS:
            if (address == 0u) return -LINUX_EFAULT;
            *(uint64_t *)(uintptr_t)address = (uint64_t)read_fs_base();
            return 0;
        case LINUX_ARCH_SET_GS:
        case LINUX_ARCH_GET_GS:
            return -LINUX_EPERM;
        default:
            return -LINUX_EINVAL;
    }
}

static long guest_fcntl(int fd, int command, uint64_t argument) {
    switch (command) {
        case 0: return hrt_linux_result((long)fcntl(fd, F_DUPFD, (int)argument));
        case 1: return hrt_linux_result((long)fcntl(fd, F_GETFD));
        case 2: return hrt_linux_result((long)fcntl(fd, F_SETFD, (int)argument));
        case 3: return hrt_linux_result((long)fcntl(fd, F_GETFL));
        case 4: return hrt_linux_result((long)fcntl(fd, F_SETFL, (int)argument));
        default: return -LINUX_ENOSYS;
    }
}

static long guest_prctl(uint64_t option, uint64_t argument) {
    if (option == LINUX_PR_SET_NAME) {
        if (argument == 0u) return -LINUX_EFAULT;
        memcpy(g_guest_process_name,
               (const void *)(uintptr_t)argument,
               sizeof(g_guest_process_name));
        g_guest_process_name[sizeof(g_guest_process_name) - 1u] = '\0';
        return 0;
    }
    if (option == LINUX_PR_GET_NAME) {
        if (argument == 0u) return -LINUX_EFAULT;
        memcpy((void *)(uintptr_t)argument,
               g_guest_process_name, sizeof(g_guest_process_name));
        return 0;
    }
    if (option == LINUX_PR_SET_VMA) return 0;
    return -LINUX_EINVAL;
}

static long dispatch_linux_syscall(x86_thread_state64_t *state) {
    uint64_t number = state->__rax;
    uint64_t a1 = state->__rdi;
    uint64_t a2 = state->__rsi;
    uint64_t a3 = state->__rdx;
    uint64_t a4 = state->__r10;
    uint64_t a5 = state->__r8;
    uint64_t a6 = state->__r9;

    switch (number) {
        case LINUX_SYS_read:
            return hrt_linux_result((long)read(
                (int)a1, (void *)(uintptr_t)a2, (size_t)a3));
        case LINUX_SYS_write:
            return hrt_linux_result((long)write(
                (int)a1, (const void *)(uintptr_t)a2, (size_t)a3));
        case LINUX_SYS_open:
            return guest_openat(LINUX_AT_FDCWD, a1, a2, a3);
        case LINUX_SYS_openat:
            return guest_openat((int)a1, a2, a3, a4);
        case LINUX_SYS_close:
            if ((int)a1 == g_sysroot_fd) return -LINUX_EBADF;
            return hrt_linux_result((long)close((int)a1));
        case LINUX_SYS_stat:
            return guest_fstatat(LINUX_AT_FDCWD, a1, a2, 0);
        case LINUX_SYS_lstat:
            return guest_fstatat(LINUX_AT_FDCWD, a1, a2,
                                 LINUX_AT_SYMLINK_NOFOLLOW);
        case LINUX_SYS_fstat:
            return guest_fstat((int)a1, a2);
        case LINUX_SYS_newfstatat:
            return guest_fstatat((int)a1, a2, a3, a4);
        case LINUX_SYS_lseek:
            return hrt_linux_result((long)lseek(
                (int)a1, (off_t)a2, (int)a3));
        case LINUX_SYS_mmap:
            return hrt_vm_mmap(a1, (size_t)a2, (uint32_t)a3,
                               a4, (int)a5, (int64_t)a6);
        case LINUX_SYS_mprotect:
            return hrt_vm_mprotect(a1, (size_t)a2, (uint32_t)a3);
        case LINUX_SYS_munmap:
            return hrt_vm_munmap(a1, (size_t)a2);
        case LINUX_SYS_brk:
            if (a1 == 0u) return (long)g_brk_current;
            if (a1 < g_brk_base || a1 > g_brk_limit) {
                return (long)g_brk_current;
            }
            if (a1 > g_brk_current) {
                uintptr_t old_end = hrt_align_up(
                    g_brk_current, g_host_page_size);
                uintptr_t new_end = hrt_align_up(
                    (uintptr_t)a1, g_host_page_size);
                if (new_end > old_end &&
                    mprotect((void *)old_end, new_end - old_end,
                             PROT_READ | PROT_WRITE) != 0) {
                    return (long)g_brk_current;
                }
            }
            g_brk_current = (uintptr_t)a1;
            return (long)g_brk_current;
        case LINUX_SYS_rt_sigaction:
            return guest_rt_sigaction((int)a1, a2, a3, (size_t)a4);
        case LINUX_SYS_rt_sigprocmask:
            return guest_rt_sigprocmask((int)a1, a2, a3, (size_t)a4);
        case LINUX_SYS_ioctl:
            return -LINUX_ENOTTY;
        case LINUX_SYS_pread64:
            return hrt_linux_result((long)pread(
                (int)a1, (void *)(uintptr_t)a2, (size_t)a3, (off_t)a4));
        case LINUX_SYS_pwrite64:
            return hrt_linux_result((long)pwrite(
                (int)a1, (const void *)(uintptr_t)a2,
                (size_t)a3, (off_t)a4));
        case LINUX_SYS_readv:
            return hrt_linux_result((long)readv(
                (int)a1, (const struct iovec *)(uintptr_t)a2, (int)a3));
        case LINUX_SYS_writev:
            return hrt_linux_result((long)writev(
                (int)a1, (const struct iovec *)(uintptr_t)a2, (int)a3));
        case LINUX_SYS_access:
            return guest_accessat(LINUX_AT_FDCWD, a1, (int)a2);
        case LINUX_SYS_faccessat:
        case LINUX_SYS_faccessat2:
            return guest_accessat((int)a1, a2, (int)a3);
        case LINUX_SYS_pipe:
            return guest_pipe2(a1, 0);
        case LINUX_SYS_pipe2:
            return guest_pipe2(a1, a2);
        case LINUX_SYS_poll:
            return hrt_linux_result((long)poll(
                (struct pollfd *)(uintptr_t)a1, (nfds_t)a2, (int)a3));
        case LINUX_SYS_sched_yield:
            return hrt_linux_result((long)sched_yield());
        case LINUX_SYS_msync:
            return hrt_linux_result((long)msync(
                (void *)(uintptr_t)a1, (size_t)a2, (int)a3));
        case LINUX_SYS_mincore:
            return hrt_linux_result((long)mincore(
                (const void *)(uintptr_t)a1, (size_t)a2,
                (char *)(uintptr_t)a3));
        case LINUX_SYS_madvise:
            return 0;
        case LINUX_SYS_dup:
            return hrt_linux_result((long)dup((int)a1));
        case LINUX_SYS_dup2:
            return hrt_linux_result((long)dup2((int)a1, (int)a2));
        case LINUX_SYS_dup3: {
            int result = dup2((int)a1, (int)a2);
            if (result >= 0 && (a3 & LINUX_O_CLOEXEC) != 0u) {
                (void)fcntl(result, F_SETFD, FD_CLOEXEC);
            }
            return hrt_linux_result((long)result);
        }
        case LINUX_SYS_nanosleep:
            return guest_nanosleep(a1, a2);
        case LINUX_SYS_getpid:
        case LINUX_SYS_gettid:
            return (long)getpid();
        case LINUX_SYS_getppid:
            return (long)getppid();
        case LINUX_SYS_getpgrp:
            return (long)getpgrp();
        case LINUX_SYS_getpgid:
            return hrt_linux_result((long)getpgid((pid_t)a1));
        case LINUX_SYS_getsid:
            return hrt_linux_result((long)getsid((pid_t)a1));
        case LINUX_SYS_exit:
        case LINUX_SYS_exit_group:
            _exit((int)(a1 & 0xffu));
        case LINUX_SYS_kill:
            return (int)a2 == 0 ? 0 : -LINUX_ENOSYS;
        case LINUX_SYS_tgkill:
            return (int)a3 == 0 ? 0 : -LINUX_ENOSYS;
        case LINUX_SYS_uname:
            return guest_uname(a1);
        case LINUX_SYS_fcntl:
            return guest_fcntl((int)a1, (int)a2, a3);
        case LINUX_SYS_fsync:
        case LINUX_SYS_fdatasync:
            return hrt_linux_result((long)fsync((int)a1));
        case LINUX_SYS_ftruncate:
            return hrt_linux_result((long)ftruncate((int)a1, (off_t)a2));
        case LINUX_SYS_getcwd:
            if (a1 == 0u) return -LINUX_EFAULT;
            if (a2 < 2u) return -LINUX_ERANGE;
            ((char *)(uintptr_t)a1)[0] = '/';
            ((char *)(uintptr_t)a1)[1] = '\0';
            return 2;
        case LINUX_SYS_chdir: {
            char path[PATH_MAX];
            long copied = copy_guest_path(a1, path);
            if (copied != 0) return copied;
            return strcmp(path, "/") == 0 ? 0 : -LINUX_ENOENT;
        }
        case LINUX_SYS_fchdir:
            return 0;
        case LINUX_SYS_readlink:
            return guest_readlinkat(
                LINUX_AT_FDCWD, a1, a2, (size_t)a3);
        case LINUX_SYS_readlinkat:
            return guest_readlinkat((int)a1, a2, a3, (size_t)a4);
        case LINUX_SYS_umask:
            return (long)umask((mode_t)a1);
        case LINUX_SYS_gettimeofday: {
            if (a1 == 0u) return 0;
            struct timeval host;
            if (gettimeofday(&host, NULL) != 0) return hrt_linux_result(-1);
            struct linux_timeval64 *output =
                (struct linux_timeval64 *)(uintptr_t)a1;
            output->tv_sec = (int64_t)host.tv_sec;
            output->tv_usec = (int64_t)host.tv_usec;
            return 0;
        }
        case LINUX_SYS_getrlimit:
            return guest_prlimit((int)a1, 0, a2);
        case LINUX_SYS_setrlimit:
            return 0;
        case LINUX_SYS_sysinfo: {
            if (a1 == 0u) return -LINUX_EFAULT;
            struct linux_sysinfo64 *information =
                (struct linux_sysinfo64 *)(uintptr_t)a1;
            memset(information, 0, sizeof(*information));
            information->mem_unit = 1;
            information->procs = 1;
            return 0;
        }
        case LINUX_SYS_getuid: return (long)getuid();
        case LINUX_SYS_getgid: return (long)getgid();
        case LINUX_SYS_geteuid: return (long)geteuid();
        case LINUX_SYS_getegid: return (long)getegid();
        case LINUX_SYS_sigaltstack:
            return guest_sigaltstack(a1, a2);
        case LINUX_SYS_personality:
            return 0;
        case LINUX_SYS_prctl:
            return guest_prctl(a1, a2);
        case LINUX_SYS_arch_prctl:
            return guest_arch_prctl(a1, a2);
        case LINUX_SYS_futex:
            return guest_futex(a1, (uint32_t)a2, (uint32_t)a3, a4);
        case LINUX_SYS_sched_getaffinity:
            if (a3 == 0u || a2 == 0u) return -LINUX_EINVAL;
            memset((void *)(uintptr_t)a3, 0, (size_t)a2);
            *(unsigned char *)(uintptr_t)a3 = 1u;
            return (long)((size_t)a2 < sizeof(uint64_t)
                              ? (size_t)a2 : sizeof(uint64_t));
        case LINUX_SYS_set_tid_address:
            return (long)getpid();
        case LINUX_SYS_clock_gettime:
            return guest_clock_gettime((int)a1, a2);
        case LINUX_SYS_clock_getres:
            return guest_clock_getres((int)a1, a2);
        case LINUX_SYS_clock_nanosleep:
            if ((int)a2 != 0) return -LINUX_ENOSYS;
            return guest_nanosleep(a3, a4);
        case LINUX_SYS_set_robust_list:
            return 0;
        case LINUX_SYS_get_robust_list:
            if (a2 != 0u) *(uint64_t *)(uintptr_t)a2 = 0;
            if (a3 != 0u) *(uint64_t *)(uintptr_t)a3 = 24;
            return 0;
        case LINUX_SYS_prlimit64:
            if ((int)a1 != 0 && (int)a1 != getpid()) return -LINUX_ESRCH;
            return guest_prlimit((int)a2, a3, a4);
        case LINUX_SYS_getcpu:
            if (a1 != 0u) *(uint32_t *)(uintptr_t)a1 = 0;
            if (a2 != 0u) *(uint32_t *)(uintptr_t)a2 = 0;
            return 0;
        case LINUX_SYS_getrandom:
            return guest_getrandom(a1, (size_t)a2);
        case LINUX_SYS_membarrier:
            return a1 == 0u ? 0 : -LINUX_ENOSYS;
        case LINUX_SYS_close_range: {
            uint64_t last = a2 > 65535u ? 65535u : a2;
            for (uint64_t descriptor = a1;
                 descriptor <= last; ++descriptor) {
                if ((int)descriptor != g_sysroot_fd && descriptor > 2u) {
                    (void)close((int)descriptor);
                }
                if (descriptor == UINT64_MAX) break;
            }
            return 0;
        }
        case LINUX_SYS_rseq:
        case LINUX_SYS_statx:
        case LINUX_SYS_openat2:
        case LINUX_SYS_clone3:
        case LINUX_SYS_mremap:
        case LINUX_SYS_select:
        case LINUX_SYS_getdents:
        case LINUX_SYS_getdents64:
        case LINUX_SYS_statfs:
        case LINUX_SYS_fstatfs:
        case LINUX_SYS_socket:
        case LINUX_SYS_connect:
        case LINUX_SYS_sendto:
        case LINUX_SYS_recvfrom:
        case LINUX_SYS_sendmsg:
        case LINUX_SYS_recvmsg:
        case LINUX_SYS_shutdown:
        case LINUX_SYS_bind:
        case LINUX_SYS_listen:
        case LINUX_SYS_getsockname:
        case LINUX_SYS_getpeername:
        case LINUX_SYS_socketpair:
        case LINUX_SYS_setsockopt:
        case LINUX_SYS_getsockopt:
        case LINUX_SYS_clone:
        case LINUX_SYS_fork:
        case LINUX_SYS_vfork:
        case LINUX_SYS_execve:
        case LINUX_SYS_wait4:
        case LINUX_SYS_unlink:
        case LINUX_SYS_getrusage:
        case LINUX_SYS_epoll_create1:
            return -LINUX_ENOSYS;
        default:
            bridge_die_syscall(number);
    }
}

static void sigill_bridge(int signal_number, siginfo_t *information,
                          void *context_pointer) {
    (void)signal_number;
    (void)information;
    if (g_in_bridge != 0) _exit(125);
    g_in_bridge = 1;
#if defined(__x86_64__)
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    const unsigned char *instruction =
        (const unsigned char *)(uintptr_t)state->__rip;
    if (instruction[0] != 0x0f || instruction[1] != 0x0b) {
        static const char message[] = "hrt-m2: unexpected SIGILL\n";
        bridge_die_literal(message, sizeof(message) - 1u, 124);
    }
    long result = dispatch_linux_syscall(state);
    state->__rax = (uint64_t)result;
    state->__rip += 2u;
    g_in_bridge = 0;
#else
#error "the M2 syscall bridge must be compiled as x86_64 Mach-O"
#endif
}

void hrt_initialize_process_state(void) {
    g_original_fs_base = read_fs_base();
    hrt_vm_initialize();
    void *reserve = mmap(NULL, HRT_M2_BRK_RESERVE, PROT_NONE,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (reserve == MAP_FAILED) hrt_fatal("reserve guest brk arena");
    g_brk_base = (uintptr_t)reserve;
    g_brk_current = g_brk_base;
    g_brk_limit = g_brk_base + HRT_M2_BRK_RESERVE;
}

void hrt_install_syscall_bridge(void) {
    void *alternate_stack = mmap(NULL, HRT_M2_SIGNAL_STACK_SIZE,
                                 PROT_READ | PROT_WRITE,
                                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (alternate_stack == MAP_FAILED) hrt_fatal("mmap M2 signal stack");
    stack_t stack;
    memset(&stack, 0, sizeof(stack));
    stack.ss_sp = alternate_stack;
    stack.ss_size = HRT_M2_SIGNAL_STACK_SIZE;
    if (sigaltstack(&stack, NULL) != 0) hrt_fatal("sigaltstack M2");

    struct sigaction action;
    memset(&action, 0, sizeof(action));
    sigemptyset(&action.sa_mask);
    action.sa_sigaction = sigill_bridge;
    action.sa_flags = SA_SIGINFO | SA_ONSTACK;
    if (sigaction(SIGILL, &action, NULL) != 0) {
        hrt_fatal("sigaction M2 SIGILL bridge");
    }
}
