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

#define LINUX_ARCH_SET_FS 0x1002
#define LINUX_ARCH_GET_FS 0x1003

static volatile sig_atomic_t g_in_handler;
static uint64_t g_host_fs_base;
static uint64_t g_guest_fs_base;

static inline uint64_t read_fs_base(void) {
    uint64_t value;
    __asm__ volatile("rdfsbase %0" : "=r"(value));
    return value;
}

static inline void write_fs_base(uint64_t value) {
    __asm__ volatile("wrfsbase %0" : : "r"(value) : "memory");
}

__attribute__((noinline, no_stack_protector))
static void sigill_handler(int signo, siginfo_t *info, void *context_pointer) {
    (void)signo;
    (void)info;
    if (g_in_handler) _exit(125);
    g_in_handler = 1;

    uint64_t interrupted_fs = read_fs_base();
    if (g_guest_fs_base != 0u && interrupted_fs != g_guest_fs_base) {
        static const char mismatch[] = "hrt-m2-tls: unexpected interrupted FS base\n";
        (void)write(STDERR_FILENO, mismatch, sizeof(mismatch) - 1u);
        _exit(121);
    }
    write_fs_base(g_host_fs_base);

#if defined(__x86_64__)
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uint64_t rip = state->__rip;
    const unsigned char *instruction = (const unsigned char *)(uintptr_t)rip;
    if (instruction[0] != 0x0f || instruction[1] != 0x0b) {
        static const char unexpected[] = "hrt-m2-tls: unexpected SIGILL\n";
        (void)write(STDERR_FILENO, unexpected, sizeof(unexpected) - 1u);
        _exit(124);
    }

    long result;
    switch (state->__rax) {
        case 1:
            result = write((int)state->__rdi,
                           (const void *)(uintptr_t)state->__rsi,
                           (size_t)state->__rdx);
            if (result < 0) result = -5;
            break;
        case 39:
            result = (long)getpid();
            break;
        case 158:
            if (state->__rdi == LINUX_ARCH_SET_FS) {
                g_guest_fs_base = state->__rsi;
                result = 0;
            } else if (state->__rdi == LINUX_ARCH_GET_FS && state->__rsi != 0u) {
                *(uint64_t *)(uintptr_t)state->__rsi = g_guest_fs_base;
                result = 0;
            } else {
                result = -22;
            }
            break;
        case 60:
        case 231:
            _exit((int)(state->__rdi & 0xffu));
        default: {
            static const char unsupported[] = "hrt-m2-tls: unsupported syscall\n";
            (void)write(STDERR_FILENO, unsupported, sizeof(unsupported) - 1u);
            _exit(126);
        }
    }
    state->__rax = (uint64_t)result;
    state->__rcx = rip + 2u;
    state->__r11 = state->__rflags;
    state->__rip = rip + 2u;

    uint64_t resume_fs = g_guest_fs_base != 0u ? g_guest_fs_base : g_host_fs_base;
    g_in_handler = 0;
    write_fs_base(resume_fs);
#else
#error "TLS test bridge must be built as x86_64 Mach-O"
#endif
}

void install_sigill_handler(void) {
    g_host_fs_base = read_fs_base();
    g_guest_fs_base = 0;

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
