#ifndef HRT_LINUX_X86_64_H
#define HRT_LINUX_X86_64_H

#include <stdint.h>

/* Linux x86-64 syscall numbers used by the M2 glibc bootstrap. */
enum {
    LINUX_SYS_read = 0,
    LINUX_SYS_write = 1,
    LINUX_SYS_open = 2,
    LINUX_SYS_close = 3,
    LINUX_SYS_stat = 4,
    LINUX_SYS_fstat = 5,
    LINUX_SYS_lstat = 6,
    LINUX_SYS_poll = 7,
    LINUX_SYS_lseek = 8,
    LINUX_SYS_mmap = 9,
    LINUX_SYS_mprotect = 10,
    LINUX_SYS_munmap = 11,
    LINUX_SYS_brk = 12,
    LINUX_SYS_rt_sigaction = 13,
    LINUX_SYS_rt_sigprocmask = 14,
    LINUX_SYS_ioctl = 16,
    LINUX_SYS_pread64 = 17,
    LINUX_SYS_pwrite64 = 18,
    LINUX_SYS_readv = 19,
    LINUX_SYS_writev = 20,
    LINUX_SYS_access = 21,
    LINUX_SYS_pipe = 22,
    LINUX_SYS_select = 23,
    LINUX_SYS_sched_yield = 24,
    LINUX_SYS_mremap = 25,
    LINUX_SYS_msync = 26,
    LINUX_SYS_mincore = 27,
    LINUX_SYS_madvise = 28,
    LINUX_SYS_dup = 32,
    LINUX_SYS_dup2 = 33,
    LINUX_SYS_nanosleep = 35,
    LINUX_SYS_getpid = 39,
    LINUX_SYS_socket = 41,
    LINUX_SYS_connect = 42,
    LINUX_SYS_sendto = 44,
    LINUX_SYS_recvfrom = 45,
    LINUX_SYS_sendmsg = 46,
    LINUX_SYS_recvmsg = 47,
    LINUX_SYS_shutdown = 48,
    LINUX_SYS_bind = 49,
    LINUX_SYS_listen = 50,
    LINUX_SYS_getsockname = 51,
    LINUX_SYS_getpeername = 52,
    LINUX_SYS_socketpair = 53,
    LINUX_SYS_setsockopt = 54,
    LINUX_SYS_getsockopt = 55,
    LINUX_SYS_clone = 56,
    LINUX_SYS_fork = 57,
    LINUX_SYS_vfork = 58,
    LINUX_SYS_execve = 59,
    LINUX_SYS_exit = 60,
    LINUX_SYS_wait4 = 61,
    LINUX_SYS_kill = 62,
    LINUX_SYS_uname = 63,
    LINUX_SYS_fcntl = 72,
    LINUX_SYS_fsync = 74,
    LINUX_SYS_fdatasync = 75,
    LINUX_SYS_ftruncate = 77,
    LINUX_SYS_getdents = 78,
    LINUX_SYS_getcwd = 79,
    LINUX_SYS_chdir = 80,
    LINUX_SYS_fchdir = 81,
    LINUX_SYS_unlink = 87,
    LINUX_SYS_readlink = 89,
    LINUX_SYS_umask = 95,
    LINUX_SYS_gettimeofday = 96,
    LINUX_SYS_getrlimit = 97,
    LINUX_SYS_getrusage = 98,
    LINUX_SYS_sysinfo = 99,
    LINUX_SYS_getuid = 102,
    LINUX_SYS_getgid = 104,
    LINUX_SYS_geteuid = 107,
    LINUX_SYS_getegid = 108,
    LINUX_SYS_getppid = 110,
    LINUX_SYS_getpgrp = 111,
    LINUX_SYS_getpgid = 121,
    LINUX_SYS_getsid = 124,
    LINUX_SYS_sigaltstack = 131,
    LINUX_SYS_personality = 135,
    LINUX_SYS_statfs = 137,
    LINUX_SYS_fstatfs = 138,
    LINUX_SYS_prctl = 157,
    LINUX_SYS_arch_prctl = 158,
    LINUX_SYS_setrlimit = 160,
    LINUX_SYS_gettid = 186,
    LINUX_SYS_futex = 202,
    LINUX_SYS_sched_getaffinity = 204,
    LINUX_SYS_getdents64 = 217,
    LINUX_SYS_set_tid_address = 218,
    LINUX_SYS_clock_gettime = 228,
    LINUX_SYS_clock_getres = 229,
    LINUX_SYS_clock_nanosleep = 230,
    LINUX_SYS_exit_group = 231,
    LINUX_SYS_tgkill = 234,
    LINUX_SYS_openat = 257,
    LINUX_SYS_newfstatat = 262,
    LINUX_SYS_readlinkat = 267,
    LINUX_SYS_faccessat = 269,
    LINUX_SYS_set_robust_list = 273,
    LINUX_SYS_get_robust_list = 274,
    LINUX_SYS_epoll_create1 = 291,
    LINUX_SYS_dup3 = 292,
    LINUX_SYS_pipe2 = 293,
    LINUX_SYS_prlimit64 = 302,
    LINUX_SYS_getcpu = 309,
    LINUX_SYS_getrandom = 318,
    LINUX_SYS_membarrier = 324,
    LINUX_SYS_statx = 332,
    LINUX_SYS_rseq = 334,
    LINUX_SYS_clone3 = 435,
    LINUX_SYS_close_range = 436,
    LINUX_SYS_openat2 = 437,
    LINUX_SYS_faccessat2 = 439,
};

/* Linux errno values. */
enum {
    LINUX_EPERM = 1,
    LINUX_ENOENT = 2,
    LINUX_ESRCH = 3,
    LINUX_EINTR = 4,
    LINUX_EIO = 5,
    LINUX_ENXIO = 6,
    LINUX_E2BIG = 7,
    LINUX_ENOEXEC = 8,
    LINUX_EBADF = 9,
    LINUX_ECHILD = 10,
    LINUX_EAGAIN = 11,
    LINUX_ENOMEM = 12,
    LINUX_EACCES = 13,
    LINUX_EFAULT = 14,
    LINUX_EBUSY = 16,
    LINUX_EEXIST = 17,
    LINUX_EXDEV = 18,
    LINUX_ENODEV = 19,
    LINUX_ENOTDIR = 20,
    LINUX_EISDIR = 21,
    LINUX_EINVAL = 22,
    LINUX_ENFILE = 23,
    LINUX_EMFILE = 24,
    LINUX_ENOTTY = 25,
    LINUX_ETXTBSY = 26,
    LINUX_EFBIG = 27,
    LINUX_ENOSPC = 28,
    LINUX_ESPIPE = 29,
    LINUX_EROFS = 30,
    LINUX_EMLINK = 31,
    LINUX_EPIPE = 32,
    LINUX_EDOM = 33,
    LINUX_ERANGE = 34,
    LINUX_ENOSYS = 38,
    LINUX_ENAMETOOLONG = 36,
    LINUX_ENOTEMPTY = 39,
    LINUX_ELOOP = 40,
    LINUX_EOVERFLOW = 75,
    LINUX_ETIMEDOUT = 110,
};

/* Linux mmap/protection flags. */
#define LINUX_PROT_NONE 0x0
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
#define LINUX_MAP_FIXED_NOREPLACE 0x100000

/* Linux open flags. */
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
#define LINUX_O_DSYNC 00010000
#define LINUX_O_DIRECTORY 00200000
#define LINUX_O_NOFOLLOW 00400000
#define LINUX_O_CLOEXEC 02000000
#define LINUX_O_PATH 010000000

#define LINUX_AT_FDCWD (-100)
#define LINUX_AT_SYMLINK_NOFOLLOW 0x100
#define LINUX_AT_EMPTY_PATH 0x1000
#define LINUX_AT_EACCESS 0x200

#define LINUX_ARCH_SET_GS 0x1001
#define LINUX_ARCH_SET_FS 0x1002
#define LINUX_ARCH_GET_FS 0x1003
#define LINUX_ARCH_GET_GS 0x1004

#define LINUX_FUTEX_WAIT 0
#define LINUX_FUTEX_WAKE 1
#define LINUX_FUTEX_PRIVATE_FLAG 128
#define LINUX_FUTEX_CLOCK_REALTIME 256
#define LINUX_FUTEX_CMD_MASK 0x7f
#define LINUX_FUTEX_WAIT_BITSET 9
#define LINUX_FUTEX_WAKE_BITSET 10

#define LINUX_PR_SET_NAME 15
#define LINUX_PR_GET_NAME 16
#define LINUX_PR_SET_VMA 0x53564d41

#define LINUX_RLIMIT_STACK 3
#define LINUX_RLIMIT_NOFILE 7
#define LINUX_RLIM_INFINITY UINT64_MAX

#define LINUX_AT_NULL 0
#define LINUX_AT_PHDR 3
#define LINUX_AT_PHENT 4
#define LINUX_AT_PHNUM 5
#define LINUX_AT_PAGESZ 6
#define LINUX_AT_BASE 7
#define LINUX_AT_FLAGS 8
#define LINUX_AT_ENTRY 9
#define LINUX_AT_UID 11
#define LINUX_AT_EUID 12
#define LINUX_AT_GID 13
#define LINUX_AT_EGID 14
#define LINUX_AT_PLATFORM 15
#define LINUX_AT_HWCAP 16
#define LINUX_AT_CLKTCK 17
#define LINUX_AT_SECURE 23
#define LINUX_AT_RANDOM 25
#define LINUX_AT_HWCAP2 26
#define LINUX_AT_RSEQ_FEATURE_SIZE 27
#define LINUX_AT_RSEQ_ALIGN 28
#define LINUX_AT_EXECFN 31
#define LINUX_AT_SYSINFO_EHDR 33
#define LINUX_AT_MINSIGSTKSZ 51

struct linux_timespec64 {
    int64_t tv_sec;
    int64_t tv_nsec;
};

struct linux_timeval64 {
    int64_t tv_sec;
    int64_t tv_usec;
};

struct linux_iovec64 {
    uint64_t iov_base;
    uint64_t iov_len;
};

struct linux_stat64 {
    uint64_t dev;
    uint64_t ino;
    uint64_t nlink;
    uint32_t mode;
    uint32_t uid;
    uint32_t gid;
    uint32_t pad0;
    uint64_t rdev;
    int64_t size;
    int64_t blksize;
    int64_t blocks;
    int64_t atime_sec;
    int64_t atime_nsec;
    int64_t mtime_sec;
    int64_t mtime_nsec;
    int64_t ctime_sec;
    int64_t ctime_nsec;
    int64_t unused[3];
};

struct linux_rlimit64 {
    uint64_t current;
    uint64_t maximum;
};

struct linux_utsname {
    char sysname[65];
    char nodename[65];
    char release[65];
    char version[65];
    char machine[65];
    char domainname[65];
};

struct linux_kernel_sigaction {
    uint64_t handler;
    uint64_t flags;
    uint64_t restorer;
    uint64_t mask;
};

struct linux_stack64 {
    uint64_t sp;
    int32_t flags;
    uint32_t padding;
    uint64_t size;
};

struct linux_sysinfo64 {
    int64_t uptime;
    uint64_t loads[3];
    uint64_t totalram;
    uint64_t freeram;
    uint64_t sharedram;
    uint64_t bufferram;
    uint64_t totalswap;
    uint64_t freeswap;
    uint16_t procs;
    uint16_t pad;
    uint32_t pad2;
    uint64_t totalhigh;
    uint64_t freehigh;
    uint32_t mem_unit;
    uint8_t padding[0];
};

#endif
