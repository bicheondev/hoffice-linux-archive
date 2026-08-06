#define _DARWIN_C_SOURCE 1
#include "syscall_internal.h"

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

#define DARWIN_THREAD_FAST_SET_CTHREAD_SELF UINT64_C(0x03000003)

static volatile sig_atomic_t g_in_handler;

static inline uintptr_t raw_set_gs(uintptr_t base) {
    uintptr_t previous;
    __asm__ volatile(
        "syscall"
        : "=a"(previous)
        : "0"(DARWIN_THREAD_FAST_SET_CTHREAD_SELF), "D"(base)
        : "rcx", "r11", "cc", "memory");
    return previous;
}

static void sigill_handler(int signo, siginfo_t *info,
                           void *context_pointer) {
    (void)signo;
    (void)info;
    if (g_in_handler) _exit(125);
    g_in_handler = 1;

#if defined(__x86_64__)
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uint64_t rip = state->__rip;
    const unsigned char *instruction =
        (const unsigned char *)(uintptr_t)rip;
    if (instruction[0] != 0x0f || instruction[1] != 0x0b) {
        static const char message[] = "hrt-m2: unexpected SIGILL\n";
        (void)write(STDERR_FILENO, message, sizeof(message) - 1u);
        _exit(124);
    }

    int entered_with_guest_gs = g_runtime.guest_gs_active;
    uintptr_t old_guest_gs = g_runtime.guest_gs_base;
    if (entered_with_guest_gs) {
        (void)raw_set_gs(g_runtime.host_gs_base);
    }

    ++g_runtime.syscall_count;
    HrtSyscallControl control;
    memset(&control, 0, sizeof(control));
    int64_t result = hrt_dispatch_linux_syscall(state, &control);
    state->__rax = (uint64_t)result;
    state->__rip = rip + 2u;

    if (control.set_guest_gs) {
        g_runtime.guest_gs_base = control.new_guest_gs;
        g_runtime.guest_gs_active = 1;
        uintptr_t previous = raw_set_gs(control.new_guest_gs);
        if (!entered_with_guest_gs) {
            g_runtime.host_gs_base = previous;
        }
    } else if (entered_with_guest_gs) {
        (void)raw_set_gs(old_guest_gs);
    }
    g_in_handler = 0;
#else
#error "hrt-m2 must be compiled as x86_64 Mach-O"
#endif
}

void install_sigill_handler(void) {
    void *altstack = mmap(NULL, HRT_ALTSTACK_SIZE,
                          PROT_READ | PROT_WRITE,
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
    if (sigaction(SIGILL, &action, NULL) != 0) {
        fatal("sigaction(SIGILL)");
    }
}
