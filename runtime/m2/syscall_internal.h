#ifndef HRT_M2_SYSCALL_INTERNAL_H
#define HRT_M2_SYSCALL_INTERNAL_H

#include "hrt_m2.h"

#include <mach/i386/thread_status.h>
#include <stdint.h>

#define HRT_LINUX_ENOSYS 38
#define HRT_LINUX_EAGAIN 11
#define HRT_LINUX_EINVAL 22
#define HRT_LINUX_EFAULT 14
#define HRT_LINUX_EBADF 9
#define HRT_LINUX_EOPNOTSUPP 95
#define HRT_LINUX_AT_FDCWD (-100)
#define HRT_LINUX_AT_SYMLINK_NOFOLLOW 0x100
#define HRT_LINUX_AT_EMPTY_PATH 0x1000
#define HRT_LINUX_ARCH_SET_FS 0x1002
#define HRT_LINUX_ARCH_GET_FS 0x1003
#define HRT_LINUX_PROT_EXEC 0x4
#define HRT_LINUX_MAP_FIXED 0x10
#define HRT_LINUX_MAP_ANONYMOUS 0x20
#define HRT_LINUX_MAP_FIXED_NOREPLACE 0x100000
#define HRT_LINUX_FUTEX_CMD_MASK 0x7f
#define HRT_LINUX_FUTEX_WAIT 0
#define HRT_LINUX_FUTEX_WAKE 1
#define HRT_LINUX_FUTEX_WAIT_BITSET 9
#define HRT_LINUX_FUTEX_WAKE_BITSET 10

typedef struct {
    uint64_t st_dev;
    uint64_t st_ino;
    uint64_t st_nlink;
    uint32_t st_mode;
    uint32_t st_uid;
    uint32_t st_gid;
    uint32_t pad0;
    uint64_t st_rdev;
    int64_t st_size;
    int64_t st_blksize;
    int64_t st_blocks;
    int64_t st_atime;
    int64_t st_atime_nsec;
    int64_t st_mtime;
    int64_t st_mtime_nsec;
    int64_t st_ctime;
    int64_t st_ctime_nsec;
    int64_t unused[3];
} HrtLinuxStat;

typedef struct {
    char sysname[65];
    char nodename[65];
    char release[65];
    char version[65];
    char machine[65];
    char domainname[65];
} HrtLinuxUtsname;

typedef struct {
    int64_t tv_sec;
    int64_t tv_nsec;
} HrtLinuxTimespec;

typedef struct {
    int64_t tv_sec;
    int64_t tv_usec;
} HrtLinuxTimeval;

typedef struct {
    uint64_t rlim_cur;
    uint64_t rlim_max;
} HrtLinuxRlimit;

typedef struct {
    int set_guest_gs;
    uintptr_t new_guest_gs;
} HrtSyscallControl;

int hrt_linux_errno(int host_error);
int64_t hrt_linux_failure(int linux_error);
int64_t hrt_host_result(long result);
void hrt_log_unsupported(uint64_t number);
int hrt_translate_open_flags(uint64_t flags);
int hrt_translate_path_checked(const char *guest_path,
                               char *host_path, size_t host_path_size);
int64_t hrt_linux_open_path(const char *guest_path, uint64_t flags,
                            uint64_t mode);
int64_t hrt_linux_stat_path(const char *guest_path, HrtLinuxStat *output,
                            int nofollow);
int64_t hrt_linux_fstat(int fd, HrtLinuxStat *output);
int64_t hrt_linux_newfstatat(int dirfd, const char *guest_path,
                             HrtLinuxStat *output, uint64_t flags);
int64_t hrt_linux_readlink_path(const char *guest_path,
                                char *buffer, size_t size);
int64_t hrt_linux_mmap(uintptr_t requested, uint64_t raw_length,
                       uint64_t protection, uint64_t flags,
                       int fd, uint64_t file_offset);
int64_t hrt_linux_brk(uintptr_t requested);
int64_t hrt_linux_prlimit(int pid, int resource,
                          const HrtLinuxRlimit *new_limit,
                          HrtLinuxRlimit *old_limit);
int64_t hrt_linux_uname(HrtLinuxUtsname *output);
int64_t hrt_linux_clock_gettime(int clock_id, HrtLinuxTimespec *output);
int64_t hrt_linux_gettimeofday(HrtLinuxTimeval *output);
int64_t hrt_linux_getrandom(void *buffer, size_t size);
int64_t hrt_linux_fcntl(int fd, int command, uint64_t argument);
int64_t hrt_dispatch_linux_syscall(x86_thread_state64_t *state,
                                   HrtSyscallControl *control);

#endif
