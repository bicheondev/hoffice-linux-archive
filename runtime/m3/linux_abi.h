#ifndef HRT_M3_LINUX_ABI_H
#define HRT_M3_LINUX_ABI_H

#include <stdint.h>

#define LINUX_SYS_READ 0
#define LINUX_SYS_WRITE 1
#define LINUX_SYS_OPEN 2
#define LINUX_SYS_CLOSE 3
#define LINUX_SYS_STAT 4
#define LINUX_SYS_FSTAT 5
#define LINUX_SYS_LSTAT 6
#define LINUX_SYS_LSEEK 8
#define LINUX_SYS_MMAP 9
#define LINUX_SYS_MPROTECT 10
#define LINUX_SYS_MUNMAP 11
#define LINUX_SYS_BRK 12
#define LINUX_SYS_RT_SIGACTION 13
#define LINUX_SYS_RT_SIGPROCMASK 14
#define LINUX_SYS_IOCTL 16
#define LINUX_SYS_PREAD64 17
#define LINUX_SYS_READV 19
#define LINUX_SYS_WRITEV 20
#define LINUX_SYS_ACCESS 21
#define LINUX_SYS_MADVISE 28
#define LINUX_SYS_GETPID 39
#define LINUX_SYS_EXIT 60
#define LINUX_SYS_UNAME 63
#define LINUX_SYS_FCNTL 72
#define LINUX_SYS_GETCWD 79
#define LINUX_SYS_READLINK 89
#define LINUX_SYS_GETTIMEOFDAY 96
#define LINUX_SYS_GETRLIMIT 97
#define LINUX_SYS_GETUID 102
#define LINUX_SYS_GETGID 104
#define LINUX_SYS_GETEUID 107
#define LINUX_SYS_GETEGID 108
#define LINUX_SYS_ARCH_PRCTL 158
#define LINUX_SYS_GETTID 186
#define LINUX_SYS_FUTEX 202
#define LINUX_SYS_SET_TID_ADDRESS 218
#define LINUX_SYS_CLOCK_GETTIME 228
#define LINUX_SYS_EXIT_GROUP 231
#define LINUX_SYS_OPENAT 257
#define LINUX_SYS_NEWFSTATAT 262
#define LINUX_SYS_READLINKAT 267
#define LINUX_SYS_SET_ROBUST_LIST 273
#define LINUX_SYS_PRLIMIT64 302
#define LINUX_SYS_GETRANDOM 318
#define LINUX_SYS_STATX 332
#define LINUX_SYS_RSEQ 334
#define LINUX_SYS_CLONE3 435
#define LINUX_SYS_FACCESSAT2 439

#define LINUX_ARCH_SET_FS UINT64_C(0x1002)
#define LINUX_ARCH_GET_FS UINT64_C(0x1003)

#define LINUX_AT_FDCWD (-100)
#define LINUX_AT_SYMLINK_NOFOLLOW 0x100
#define LINUX_AT_EMPTY_PATH 0x1000

#define LINUX_O_ACCMODE 00000003
#define LINUX_O_RDONLY 00000000
#define LINUX_O_WRONLY 00000001
#define LINUX_O_RDWR 00000002
#define LINUX_O_CREAT 00000100
#define LINUX_O_EXCL 00000200
#define LINUX_O_NOCTTY 00000400
#define LINUX_O_TRUNC 00001000
#define LINUX_O_APPEND 00002000
#define LINUX_O_NONBLOCK 00004000
#define LINUX_O_DIRECTORY 00200000
#define LINUX_O_NOFOLLOW 00400000
#define LINUX_O_CLOEXEC 02000000

#define LINUX_PROT_READ 0x1
#define LINUX_PROT_WRITE 0x2
#define LINUX_PROT_EXEC 0x4

#define LINUX_MAP_SHARED 0x01
#define LINUX_MAP_PRIVATE 0x02
#define LINUX_MAP_FIXED 0x10
#define LINUX_MAP_ANONYMOUS 0x20
#define LINUX_MAP_GROWSDOWN 0x0100
#define LINUX_MAP_DENYWRITE 0x0800
#define LINUX_MAP_EXECUTABLE 0x1000
#define LINUX_MAP_NORESERVE 0x4000
#define LINUX_MAP_STACK 0x20000
#define LINUX_MAP_FIXED_NOREPLACE 0x100000

#define LINUX_F_GETFD 1
#define LINUX_F_SETFD 2
#define LINUX_F_GETFL 3
#define LINUX_F_SETFL 4

#define LINUX_FUTEX_WAIT 0
#define LINUX_FUTEX_WAKE 1
#define LINUX_FUTEX_PRIVATE_FLAG 128
#define LINUX_FUTEX_CMD_MASK 0x7f

#define LINUX_RLIMIT_STACK 3

#define LINUX_EPERM 1
#define LINUX_ENOENT 2
#define LINUX_ESRCH 3
#define LINUX_EINTR 4
#define LINUX_EIO 5
#define LINUX_EBADF 9
#define LINUX_EAGAIN 11
#define LINUX_ENOMEM 12
#define LINUX_EACCES 13
#define LINUX_EFAULT 14
#define LINUX_EBUSY 16
#define LINUX_EEXIST 17
#define LINUX_ENODEV 19
#define LINUX_ENOTDIR 20
#define LINUX_EISDIR 21
#define LINUX_EINVAL 22
#define LINUX_ENFILE 23
#define LINUX_EMFILE 24
#define LINUX_ENOTTY 25
#define LINUX_EFBIG 27
#define LINUX_ENOSPC 28
#define LINUX_ESPIPE 29
#define LINUX_EROFS 30
#define LINUX_EPIPE 32
#define LINUX_ERANGE 34
#define LINUX_ENAMETOOLONG 36
#define LINUX_ENOSYS 38
#define LINUX_ENOTEMPTY 39
#define LINUX_ELOOP 40
#define LINUX_EOVERFLOW 75

#define LINUX_UTS_FIELD_SIZE 65

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
    int64_t st_atime_sec;
    int64_t st_atime_nsec;
    int64_t st_mtime_sec;
    int64_t st_mtime_nsec;
    int64_t st_ctime_sec;
    int64_t st_ctime_nsec;
    int64_t reserved[3];
} LinuxStat;

typedef struct {
    int64_t tv_sec;
    int64_t tv_nsec;
} LinuxTimespec;

typedef struct {
    int64_t tv_sec;
    int64_t tv_usec;
} LinuxTimeval;

typedef struct {
    uint64_t rlim_cur;
    uint64_t rlim_max;
} LinuxRlimit;

typedef struct {
    char sysname[LINUX_UTS_FIELD_SIZE];
    char nodename[LINUX_UTS_FIELD_SIZE];
    char release[LINUX_UTS_FIELD_SIZE];
    char version[LINUX_UTS_FIELD_SIZE];
    char machine[LINUX_UTS_FIELD_SIZE];
    char domainname[LINUX_UTS_FIELD_SIZE];
} LinuxUtsname;

_Static_assert(sizeof(LinuxStat) == 144u, "Linux x86-64 stat size");
_Static_assert(sizeof(LinuxTimespec) == 16u, "Linux x86-64 timespec size");
_Static_assert(sizeof(LinuxTimeval) == 16u, "Linux x86-64 timeval size");
_Static_assert(sizeof(LinuxRlimit) == 16u, "Linux x86-64 rlimit size");

#endif
