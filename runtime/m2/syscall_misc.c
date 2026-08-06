#define _DARWIN_C_SOURCE 1
#include "syscall_internal.h"

#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define HRT_LINUX_RLIM_INFINITY UINT64_MAX

static int host_resource(int linux_resource) {
    switch (linux_resource) {
        case 0: return RLIMIT_CPU;
        case 1: return RLIMIT_FSIZE;
        case 2: return RLIMIT_DATA;
        case 3: return RLIMIT_STACK;
        case 4: return RLIMIT_CORE;
        case 5: return RLIMIT_RSS;
#ifdef RLIMIT_NPROC
        case 6: return RLIMIT_NPROC;
#endif
        case 7: return RLIMIT_NOFILE;
#ifdef RLIMIT_MEMLOCK
        case 8: return RLIMIT_MEMLOCK;
#endif
#ifdef RLIMIT_AS
        case 9: return RLIMIT_AS;
#endif
        default: return -1;
    }
}

static uint64_t linux_rlim(rlim_t value) {
    return value == RLIM_INFINITY ? HRT_LINUX_RLIM_INFINITY
                                  : (uint64_t)value;
}

static rlim_t host_rlim(uint64_t value) {
    return value == HRT_LINUX_RLIM_INFINITY ? RLIM_INFINITY
                                            : (rlim_t)value;
}

int64_t hrt_linux_prlimit(int pid, int resource,
                          const HrtLinuxRlimit *new_limit,
                          HrtLinuxRlimit *old_limit) {
    if (pid != 0 && pid != getpid()) return hrt_linux_failure(3);
    int host = host_resource(resource);
    if (host < 0) return hrt_linux_failure(HRT_LINUX_EINVAL);
    struct rlimit limit;
    if (old_limit != NULL) {
        if (getrlimit(host, &limit) != 0) {
            return hrt_linux_failure(hrt_linux_errno(errno));
        }
        old_limit->rlim_cur = linux_rlim(limit.rlim_cur);
        old_limit->rlim_max = linux_rlim(limit.rlim_max);
    }
    if (new_limit != NULL) {
        limit.rlim_cur = host_rlim(new_limit->rlim_cur);
        limit.rlim_max = host_rlim(new_limit->rlim_max);
        if (setrlimit(host, &limit) != 0) {
            return hrt_linux_failure(hrt_linux_errno(errno));
        }
    }
    return 0;
}

int64_t hrt_linux_uname(HrtLinuxUtsname *output) {
    if (output == NULL) return hrt_linux_failure(HRT_LINUX_EFAULT);
    memset(output, 0, sizeof(*output));
    memcpy(output->sysname, "Linux", 6);
    memcpy(output->nodename, "hrt-macos", 10);
    memcpy(output->release, "6.1.0-hrt", 10);
    memcpy(output->version, "#1 HRT clean-room", 18);
    memcpy(output->machine, "x86_64", 7);
    memcpy(output->domainname, "localdomain", 12);
    return 0;
}

int64_t hrt_linux_clock_gettime(int clock_id, HrtLinuxTimespec *output) {
    if (output == NULL) return hrt_linux_failure(HRT_LINUX_EFAULT);
    clockid_t host_clock;
    switch (clock_id) {
        case 0: host_clock = CLOCK_REALTIME; break;
        case 1: host_clock = CLOCK_MONOTONIC; break;
#ifdef CLOCK_PROCESS_CPUTIME_ID
        case 2: host_clock = CLOCK_PROCESS_CPUTIME_ID; break;
#endif
#ifdef CLOCK_THREAD_CPUTIME_ID
        case 3: host_clock = CLOCK_THREAD_CPUTIME_ID; break;
#endif
        default: return hrt_linux_failure(HRT_LINUX_EINVAL);
    }
    struct timespec value;
    if (clock_gettime(host_clock, &value) != 0) {
        return hrt_linux_failure(hrt_linux_errno(errno));
    }
    output->tv_sec = value.tv_sec;
    output->tv_nsec = value.tv_nsec;
    return 0;
}

int64_t hrt_linux_gettimeofday(HrtLinuxTimeval *output) {
    if (output == NULL) return 0;
    struct timeval value;
    if (gettimeofday(&value, NULL) != 0) {
        return hrt_linux_failure(hrt_linux_errno(errno));
    }
    output->tv_sec = value.tv_sec;
    output->tv_usec = value.tv_usec;
    return 0;
}

int64_t hrt_linux_getrandom(void *buffer, size_t size) {
    static uint64_t state = UINT64_C(0x8d3f6a1957c42be1);
    if (buffer == NULL && size != 0u) {
        return hrt_linux_failure(HRT_LINUX_EFAULT);
    }
    unsigned char *bytes = buffer;
    for (size_t index = 0; index < size; ++index) {
        uint64_t value = state;
        value ^= value << 13;
        value ^= value >> 7;
        value ^= value << 17;
        state = value;
        bytes[index] = (unsigned char)value;
    }
    return (int64_t)size;
}
