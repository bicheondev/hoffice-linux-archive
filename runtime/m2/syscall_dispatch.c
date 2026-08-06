#define _DARWIN_C_SOURCE 1
#include "syscall_internal.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <string.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

#define HRT_LINUX_O_NONBLOCK 0x800u
#define HRT_LINUX_O_CLOEXEC 0x80000u
#define HRT_LINUX_ENOTSOCK 88

static int set_pipe_flags(int fd, uint64_t flags) {
    if ((flags & HRT_LINUX_O_NONBLOCK) != 0u) {
        int status = fcntl(fd, F_GETFL);
        if (status < 0 || fcntl(fd, F_SETFL, status | O_NONBLOCK) < 0) {
            return -1;
        }
    }
    if ((flags & HRT_LINUX_O_CLOEXEC) != 0u) {
        int descriptor = fcntl(fd, F_GETFD);
        if (descriptor < 0 ||
            fcntl(fd, F_SETFD, descriptor | FD_CLOEXEC) < 0) {
            return -1;
        }
    }
    return 0;
}

static int64_t linux_pipe2(int *guest_pipe, uint64_t flags) {
    if (guest_pipe == NULL) return hrt_linux_failure(HRT_LINUX_EFAULT);
    if ((flags & ~(HRT_LINUX_O_NONBLOCK | HRT_LINUX_O_CLOEXEC)) != 0u) {
        return hrt_linux_failure(HRT_LINUX_EINVAL);
    }

    int descriptors[2];
    if (pipe(descriptors) != 0) {
        return hrt_linux_failure(hrt_linux_errno(errno));
    }
    if (set_pipe_flags(descriptors[0], flags) != 0 ||
        set_pipe_flags(descriptors[1], flags) != 0) {
        int saved = errno;
        (void)close(descriptors[0]);
        (void)close(descriptors[1]);
        errno = saved;
        return hrt_linux_failure(hrt_linux_errno(errno));
    }

    guest_pipe[0] = descriptors[0];
    guest_pipe[1] = descriptors[1];
    return 0;
}

int64_t hrt_dispatch_linux_syscall(x86_thread_state64_t *state,
                                   HrtSyscallControl *control) {
    uint64_t number = state->__rax;
    uint64_t a1 = state->__rdi;
    uint64_t a2 = state->__rsi;
    uint64_t a3 = state->__rdx;
    uint64_t a4 = state->__r10;
    uint64_t a5 = state->__r8;
    uint64_t a6 = state->__r9;

    switch (number) {
        case 0:
            return hrt_host_result(read((int)a1, (void *)(uintptr_t)a2,
                                        (size_t)a3));
        case 1:
            return hrt_host_result(write((int)a1,
                                         (const void *)(uintptr_t)a2,
                                         (size_t)a3));
        case 2:
            return hrt_linux_open_path((const char *)(uintptr_t)a1,
                                       a2, a3);
        case 3: {
            int result = close((int)a1);
            if (result == 0) clear_fd_path((int)a1);
            return hrt_host_result(result);
        }
        case 4:
            return hrt_linux_stat_path((const char *)(uintptr_t)a1,
                                       (HrtLinuxStat *)(uintptr_t)a2, 0);
        case 5:
            return hrt_linux_fstat((int)a1,
                                   (HrtLinuxStat *)(uintptr_t)a2);
        case 6:
            return hrt_linux_stat_path((const char *)(uintptr_t)a1,
                                       (HrtLinuxStat *)(uintptr_t)a2, 1);
        case 7:
            return hrt_host_result(poll(
                (struct pollfd *)(uintptr_t)a1,
                (nfds_t)a2,
                (int)a3));
        case 8:
            return hrt_host_result(lseek((int)a1, (off_t)a2, (int)a3));
        case 9:
            return hrt_linux_mmap((uintptr_t)a1, a2, a3, a4,
                                  (int)a5, a6);
        case 10:
            if ((a3 & HRT_LINUX_PROT_EXEC) != 0u) {
                patch_guest_mappings((uintptr_t)a1, (size_t)a2);
            }
            return 0;
        case 11:
            return 0;
        case 12:
            return hrt_linux_brk((uintptr_t)a1);
        case 13:
            if (a4 != 8u) return hrt_linux_failure(HRT_LINUX_EINVAL);
            if (a3 != 0u) memset((void *)(uintptr_t)a3, 0, 32u);
            return 0;
        case 14:
            if (a4 != 8u) return hrt_linux_failure(HRT_LINUX_EINVAL);
            if (a3 != 0u) memset((void *)(uintptr_t)a3, 0, 8u);
            return 0;
        case 16:
            return hrt_linux_failure(25);
        case 17:
            return hrt_host_result(pread((int)a1,
                                         (void *)(uintptr_t)a2,
                                         (size_t)a3, (off_t)a4));
        case 19:
            return hrt_host_result(readv(
                (int)a1, (const struct iovec *)(uintptr_t)a2, (int)a3));
        case 20:
            return hrt_host_result(writev(
                (int)a1, (const struct iovec *)(uintptr_t)a2, (int)a3));
        case 21: {
            char host_path[HRT_MAX_PATH];
            if (hrt_translate_path_checked((const char *)(uintptr_t)a1,
                    host_path, sizeof(host_path)) != 0) {
                return hrt_linux_failure(hrt_linux_errno(errno));
            }
            return hrt_host_result(access(host_path, (int)a2));
        }
        case 24:
        case 28:
            return 0;
        case 32: {
            int result = dup((int)a1);
            if (result >= 0) copy_fd_path((int)a1, result);
            return hrt_host_result(result);
        }
        case 33: {
            int result = dup2((int)a1, (int)a2);
            if (result >= 0) copy_fd_path((int)a1, result);
            return hrt_host_result(result);
        }
        case 35: {
            const HrtLinuxTimespec *request =
                (const HrtLinuxTimespec *)(uintptr_t)a1;
            if (request == NULL) {
                return hrt_linux_failure(HRT_LINUX_EFAULT);
            }
            struct timespec host_request = {
                .tv_sec = (time_t)request->tv_sec,
                .tv_nsec = (long)request->tv_nsec,
            };
            return hrt_host_result(nanosleep(&host_request, NULL));
        }
        case 39:
            return getpid();
        case 52:
            return hrt_linux_failure(HRT_LINUX_ENOTSOCK);
        case 60:
        case 231:
            _exit((int)(a1 & 0xffu));
        case 63:
            return hrt_linux_uname((HrtLinuxUtsname *)(uintptr_t)a1);
        case 72:
            return hrt_linux_fcntl((int)a1, (int)a2, a3);
        case 79: {
            char *output = (char *)(uintptr_t)a1;
            size_t size = (size_t)a2;
            if (output == NULL) return hrt_linux_failure(HRT_LINUX_EFAULT);
            if (size < 2u) return hrt_linux_failure(34);
            output[0] = '/';
            output[1] = '\0';
            return 2;
        }
        case 89:
            return hrt_linux_readlink_path(
                (const char *)(uintptr_t)a1,
                (char *)(uintptr_t)a2, (size_t)a3);
        case 96:
            return hrt_linux_gettimeofday(
                (HrtLinuxTimeval *)(uintptr_t)a1);
        case 97:
            return hrt_linux_prlimit(0, (int)a1, NULL,
                (HrtLinuxRlimit *)(uintptr_t)a2);
        case 102:
            return getuid();
        case 104:
            return getgid();
        case 107:
            return geteuid();
        case 108:
            return getegid();
        case 110:
            return getppid();
        case 131:
        case 135:
        case 157:
            return 0;
        case 158:
            if (a1 == HRT_LINUX_ARCH_SET_FS) {
                control->set_guest_gs = 1;
                control->new_guest_gs = (uintptr_t)a2;
                return 0;
            }
            if (a1 == HRT_LINUX_ARCH_GET_FS) {
                if (a2 == 0u) {
                    return hrt_linux_failure(HRT_LINUX_EFAULT);
                }
                *(uint64_t *)(uintptr_t)a2 =
                    (uint64_t)g_runtime.guest_gs_base;
                return 0;
            }
            return hrt_linux_failure(HRT_LINUX_EINVAL);
        case 186:
            return getpid();
        case 202: {
            int operation = (int)(a2 & HRT_LINUX_FUTEX_CMD_MASK);
            if (operation == HRT_LINUX_FUTEX_WAKE ||
                operation == HRT_LINUX_FUTEX_WAKE_BITSET) {
                return 0;
            }
            if (operation == HRT_LINUX_FUTEX_WAIT ||
                operation == HRT_LINUX_FUTEX_WAIT_BITSET) {
                return hrt_linux_failure(HRT_LINUX_EAGAIN);
            }
            return hrt_linux_failure(HRT_LINUX_ENOSYS);
        }
        case 204: {
            if (a3 == 0u || a2 == 0u) {
                return hrt_linux_failure(HRT_LINUX_EINVAL);
            }
            size_t size = (size_t)a2;
            memset((void *)(uintptr_t)a3, 0, size);
            ((unsigned char *)(uintptr_t)a3)[0] = 1u;
            return (int64_t)(size < sizeof(uint64_t)
                ? size : sizeof(uint64_t));
        }
        case 218:
            g_runtime.clear_child_tid = (uintptr_t)a1;
            return getpid();
        case 228:
            return hrt_linux_clock_gettime(
                (int)a1, (HrtLinuxTimespec *)(uintptr_t)a2);
        case 229: {
            HrtLinuxTimespec *output =
                (HrtLinuxTimespec *)(uintptr_t)a2;
            if (output == NULL) {
                return hrt_linux_failure(HRT_LINUX_EFAULT);
            }
            output->tv_sec = 0;
            output->tv_nsec = 1000;
            return 0;
        }
        case 257:
            if ((int64_t)a1 != HRT_LINUX_AT_FDCWD &&
                ((const char *)(uintptr_t)a2)[0] != '/') {
                return hrt_linux_failure(HRT_LINUX_EOPNOTSUPP);
            }
            return hrt_linux_open_path(
                (const char *)(uintptr_t)a2, a3, a4);
        case 262:
            return hrt_linux_newfstatat(
                (int)a1, (const char *)(uintptr_t)a2,
                (HrtLinuxStat *)(uintptr_t)a3, a4);
        case 267:
            if ((int64_t)a1 != HRT_LINUX_AT_FDCWD &&
                ((const char *)(uintptr_t)a2)[0] != '/') {
                return hrt_linux_failure(HRT_LINUX_EOPNOTSUPP);
            }
            return hrt_linux_readlink_path(
                (const char *)(uintptr_t)a2,
                (char *)(uintptr_t)a3, (size_t)a4);
        case 269: {
            if ((int64_t)a1 != HRT_LINUX_AT_FDCWD &&
                ((const char *)(uintptr_t)a2)[0] != '/') {
                return hrt_linux_failure(HRT_LINUX_EOPNOTSUPP);
            }
            char host_path[HRT_MAX_PATH];
            if (hrt_translate_path_checked((const char *)(uintptr_t)a2,
                    host_path, sizeof(host_path)) != 0) {
                return hrt_linux_failure(hrt_linux_errno(errno));
            }
            return hrt_host_result(access(host_path, (int)a3));
        }
        case 273:
            return 0;
        case 290:
            return hrt_linux_failure(HRT_LINUX_ENOSYS);
        case 293:
            return linux_pipe2((int *)(uintptr_t)a1, a2);
        case 302:
            return hrt_linux_prlimit(
                (int)a1, (int)a2,
                (const HrtLinuxRlimit *)(uintptr_t)a3,
                (HrtLinuxRlimit *)(uintptr_t)a4);
        case 309:
            if (a1 != 0u) *(uint32_t *)(uintptr_t)a1 = 0u;
            if (a2 != 0u) *(uint32_t *)(uintptr_t)a2 = 0u;
            return 0;
        case 318:
            return hrt_linux_getrandom((void *)(uintptr_t)a1,
                                       (size_t)a2);
        case 332:
        case 334:
        case 439:
            return hrt_linux_failure(HRT_LINUX_ENOSYS);
        default:
            ++g_runtime.unsupported_count;
            hrt_log_unsupported(number);
            return hrt_linux_failure(HRT_LINUX_ENOSYS);
    }
}
