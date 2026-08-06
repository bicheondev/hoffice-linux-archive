#define _DARWIN_C_SOURCE 1
#include "hrt_m2.h"

#include <mach/i386/thread_status.h>
#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/ucontext.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

#define DARWIN_BSD_SYSCALL(number) (UINT64_C(0x02000000) + (number))
#define DARWIN_MACHDEP_SET_GS UINT64_C(0x03000003)

#define DARWIN_SYS_EXIT UINT64_C(1)
#define DARWIN_SYS_WRITE UINT64_C(4)
#define DARWIN_SYS_GETPID UINT64_C(20)

#define LINUX_SYS_WRITE UINT64_C(1)
#define LINUX_SYS_ARCH_PRCTL UINT64_C(158)
#define LINUX_SYS_GETPID UINT64_C(39)
#define LINUX_SYS_EXIT UINT64_C(60)
#define LINUX_SYS_EXIT_GROUP UINT64_C(231)

#define LINUX_ARCH_SET_FS UINT64_C(0x1002)
#define LINUX_ARCH_GET_FS UINT64_C(0x1003)
#define LINUX_EFAULT INT64_C(14)
#define LINUX_EINVAL INT64_C(22)

static volatile sig_atomic_t g_in_handler;
static uintptr_t g_guest_fs_base;

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

static inline uintptr_t raw_set_guest_gs(uintptr_t base) {
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

__attribute__((noreturn))
static void fail_from_signal(const char *message, size_t length, int status) {
    (void)raw_bsd_syscall3(DARWIN_SYS_WRITE, STDERR_FILENO,
                           (uint64_t)(uintptr_t)message, length);
    raw_exit(status);
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
        static const char message[] = "hrt-m2: unexpected SIGILL\n";
        fail_from_signal(message, sizeof(message) - 1u, 124);
    }

    switch (state->__rax) {
        case LINUX_SYS_WRITE:
            state->__rax = (uint64_t)raw_bsd_syscall3(
                DARWIN_SYS_WRITE, state->__rdi, state->__rsi, state->__rdx);
            break;
        case LINUX_SYS_GETPID:
            state->__rax = (uint64_t)raw_bsd_syscall0(DARWIN_SYS_GETPID);
            break;
        case LINUX_SYS_ARCH_PRCTL:
            switch (state->__rdi) {
                case LINUX_ARCH_SET_FS:
                    g_guest_fs_base = (uintptr_t)state->__rsi;
                    (void)raw_set_guest_gs(g_guest_fs_base);
                    state->__rax = 0u;
                    break;
                case LINUX_ARCH_GET_FS:
                    if (state->__rsi == 0u) {
                        state->__rax = (uint64_t)-LINUX_EFAULT;
                    } else {
                        *(uint64_t *)(uintptr_t)state->__rsi =
                            (uint64_t)g_guest_fs_base;
                        state->__rax = 0u;
                    }
                    break;
                default:
                    state->__rax = (uint64_t)-LINUX_EINVAL;
                    break;
            }
            break;
        case LINUX_SYS_EXIT:
        case LINUX_SYS_EXIT_GROUP:
            raw_exit((int)(state->__rdi & 0xffu));
        default: {
            static const char message[] =
                "hrt-m2: unsupported Linux syscall in TLS milestone\n";
            fail_from_signal(message, sizeof(message) - 1u, 126);
        }
    }

    state->__rip = rip + 2u;
    g_in_handler = 0;
#else
#error "hrt-m2 must be built as x86_64 Mach-O"
#endif
}

void install_sigill_handler(void) {
    void *altstack = mmap(NULL, HRT_ALTSTACK_SIZE, PROT_READ | PROT_WRITE,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (altstack == MAP_FAILED) fatal("mmap alternate signal stack");

    stack_t stack;
    memset(&stack, 0, sizeof(stack));
    stack.ss_sp = altstack;
    stack.ss_size = HRT_ALTSTACK_SIZE;
    if (sigaltstack(&stack, NULL) != 0) fatal("sigaltstack");

    struct sigaction action;
    memset(&action, 0, sizeof(action));
    sigemptyset(&action.sa_mask);
    action.sa_sigaction = sigill_handler;
    action.sa_flags = SA_SIGINFO | SA_ONSTACK;
    if (sigaction(SIGILL, &action, NULL) != 0) fatal("sigaction(SIGILL)");
}
