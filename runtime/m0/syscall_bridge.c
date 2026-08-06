#define _DARWIN_C_SOURCE 1
#include "hrt_m0.h"

#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/ucontext.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

static volatile sig_atomic_t g_in_handler;

static long linux_result(long host_result) {
    return host_result == -1 ? -(long)errno : host_result;
}

static void fail_from_signal(const char *message, size_t length, int status) {
    (void)write(STDERR_FILENO, message, length);
    _exit(status);
}

static void sigill_handler(int signo, siginfo_t *info, void *context_pointer) {
    (void)signo;
    (void)info;
    if (g_in_handler) _exit(125);
    g_in_handler = 1;

#if defined(__x86_64__)
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uint64_t rip = state->__rip;
    const unsigned char *instruction = (const unsigned char *)(uintptr_t)rip;
    if (instruction[0] != 0x0f || instruction[1] != 0x0b) {
        static const char message[] = "hrt-m0: unexpected SIGILL\n";
        fail_from_signal(message, sizeof(message) - 1u, 124);
    }

    switch (state->__rax) {
        case 1: /* Linux write */
            state->__rax = (uint64_t)linux_result((long)write(
                (int)state->__rdi,
                (const void *)(uintptr_t)state->__rsi,
                (size_t)state->__rdx));
            break;
        case 39: /* Linux getpid */
            state->__rax = (uint64_t)getpid();
            break;
        case 60:  /* Linux exit */
        case 231: /* Linux exit_group */
            _exit((int)(state->__rdi & 0xffu));
        default: {
            static const char message[] = "hrt-m0: unsupported Linux syscall\n";
            fail_from_signal(message, sizeof(message) - 1u, 126);
        }
    }
    state->__rip = rip + 2u;
    g_in_handler = 0;
#else
#error "hrt-m0 must be built as x86_64 Mach-O"
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
