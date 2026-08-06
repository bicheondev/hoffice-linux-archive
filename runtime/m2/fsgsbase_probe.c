#define _DARWIN_C_SOURCE 1
#include <inttypes.h>
#include <mach/i386/thread_status.h>
#include <setjmp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/ucontext.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

#define DARWIN_THREAD_FAST_SET_CTHREAD_SELF UINT64_C(0x03000003)
#define DARWIN_EXIT UINT64_C(0x02000001)
#define TLS_MARKER_A UINT64_C(0x4852544d32544c41) /* HRTM2TLA */
#define TLS_MARKER_B UINT64_C(0x4852544d32544c42) /* HRTM2TLB */

typedef struct {
    _Alignas(64) uint64_t guest_tls_a[8];
    _Alignas(64) uint64_t guest_tls_b[8];
    volatile uint64_t initial_set_return;
    volatile uint64_t before_signal_gs0;
    volatile uint64_t handler_gs0;
    volatile uint64_t handler_set_b_return;
    volatile uint64_t after_signal_gs0;
    volatile uint64_t handler_rip;
    volatile uint32_t handler_entered;
    volatile uint32_t handler_instruction_ok;
} ProbeShared;

static sigjmp_buf g_recovery;
static volatile sig_atomic_t g_direct_fs_trapped;
static ProbeShared *g_shared;

static void direct_fs_sigill(int signo) {
    (void)signo;
    g_direct_fs_trapped = 1;
    siglongjmp(g_recovery, 1);
}

static inline uintptr_t read_fs_base(void) {
    uintptr_t value;
    __asm__ volatile("rdfsbase %0" : "=r"(value));
    return value;
}

static inline void write_fs_base(uintptr_t value) {
    __asm__ volatile("wrfsbase %0" : : "r"(value) : "memory");
}

static inline uint64_t read_fs_zero(void) {
    uint64_t value;
    __asm__ volatile("movq %%fs:0, %0" : "=r"(value));
    return value;
}

static inline uint64_t read_gs_zero(void) {
    uint64_t value;
    __asm__ volatile("movq %%gs:0, %0" : "=r"(value));
    return value;
}

static inline uintptr_t raw_set_gs(uintptr_t base) {
    uintptr_t result;
    __asm__ volatile(
        "syscall"
        : "=a"(result)
        : "0"(DARWIN_THREAD_FAST_SET_CTHREAD_SELF), "D"(base)
        : "rcx", "r11", "cc", "memory");
    return result;
}

static void guest_sigill(int signo, siginfo_t *info, void *context_pointer) {
    (void)signo;
    (void)info;
#if defined(__x86_64__)
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uint64_t rip = state->__rip;
    const unsigned char *instruction =
        (const unsigned char *)(uintptr_t)rip;

    g_shared->handler_gs0 = read_gs_zero();
    g_shared->handler_rip = rip;
    g_shared->handler_instruction_ok =
        instruction[0] == 0x0f && instruction[1] == 0x0b;
    g_shared->handler_entered = 1u;
    g_shared->handler_set_b_return = raw_set_gs(
        (uintptr_t)&g_shared->guest_tls_b[0]);
    state->__rip = rip + 2u;
#else
#error "M2 TLS probe must be compiled as x86_64"
#endif
}

__attribute__((noreturn, noinline))
static void child_switch_signal_and_exit(ProbeShared *shared) {
    uintptr_t guest_base = (uintptr_t)&shared->guest_tls_a[0];
    volatile uint64_t *set_return = &shared->initial_set_return;
    volatile uint64_t *before = &shared->before_signal_gs0;
    volatile uint64_t *after = &shared->after_signal_gs0;

    __asm__ volatile(
        "movq %[guest], %%rdi\n\t"
        "movq %[set_number], %%rax\n\t"
        "syscall\n\t"
        "movq %%rax, (%[set_return])\n\t"
        "movq %%gs:0, %%r8\n\t"
        "movq %%r8, (%[before])\n\t"
        "ud2\n\t"
        "movq %%gs:0, %%r8\n\t"
        "movq %%r8, (%[after])\n\t"
        "xorl %%edi, %%edi\n\t"
        "movq %[exit_number], %%rax\n\t"
        "syscall\n\t"
        "ud2\n\t"
        :
        : [guest] "r"(guest_base),
          [set_return] "r"(set_return),
          [before] "r"(before),
          [after] "r"(after),
          [set_number] "i"(DARWIN_THREAD_FAST_SET_CTHREAD_SELF),
          [exit_number] "i"(DARWIN_EXIT)
        : "rax", "rdi", "rcx", "r8", "r11", "cc", "memory");
    __builtin_unreachable();
}

static int install_handler(void (*handler)(int, siginfo_t *, void *)) {
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    sigemptyset(&action.sa_mask);
    action.sa_sigaction = handler;
    action.sa_flags = SA_SIGINFO;
    return sigaction(SIGILL, &action, NULL);
}

int main(void) {
    struct sigaction direct_action;
    memset(&direct_action, 0, sizeof(direct_action));
    sigemptyset(&direct_action.sa_mask);
    direct_action.sa_handler = direct_fs_sigill;
    if (sigaction(SIGILL, &direct_action, NULL) != 0) {
        perror("sigaction direct FS");
        return 1;
    }

    int direct_fs_supported = 0;
    uintptr_t original_fs = 0;
    if (sigsetjmp(g_recovery, 1) == 0) {
        original_fs = read_fs_base();
        uint64_t fs_test = TLS_MARKER_A;
        write_fs_base((uintptr_t)&fs_test);
        direct_fs_supported = read_fs_zero() == TLS_MARKER_A;
        write_fs_base(original_fs);
    }

    ProbeShared *shared = mmap(NULL, sizeof(*shared),
                               PROT_READ | PROT_WRITE,
                               MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (shared == MAP_FAILED) {
        perror("mmap shared probe state");
        return 1;
    }
    memset(shared, 0, sizeof(*shared));
    shared->guest_tls_a[0] = TLS_MARKER_A;
    shared->guest_tls_b[0] = TLS_MARKER_B;
    g_shared = shared;

    if (install_handler(guest_sigill) != 0) {
        perror("sigaction guest SIGILL");
        return 1;
    }

    pid_t child = fork();
    if (child < 0) {
        perror("fork");
        return 1;
    }
    if (child == 0) child_switch_signal_and_exit(shared);

    int child_status = 0;
    if (waitpid(child, &child_status, 0) != child) {
        perror("waitpid");
        return 1;
    }

    printf("HRT M2 probe: direct-fs=%s trapped=%s original-fs=0x%" PRIxPTR "\n",
           direct_fs_supported ? "yes" : "no",
           g_direct_fs_trapped ? "yes" : "no", original_fs);
    printf("HRT M2 probe: initial-set-return=0x%016" PRIx64
           " guest-gs-before=0x%016" PRIx64 "\n",
           shared->initial_set_return, shared->before_signal_gs0);
    printf("HRT M2 probe: handler-entered=%u instruction-ok=%u"
           " handler-gs0=0x%016" PRIx64 " rip=0x%016" PRIx64 "\n",
           shared->handler_entered, shared->handler_instruction_ok,
           shared->handler_gs0, shared->handler_rip);
    printf("HRT M2 probe: handler-set-b-return=0x%016" PRIx64 "\n",
           shared->handler_set_b_return);
    printf("HRT M2 probe: guest-gs-after=0x%016" PRIx64 "\n",
           shared->after_signal_gs0);

    int child_ok = WIFEXITED(child_status) && WEXITSTATUS(child_status) == 0;
    uintptr_t guest_a = (uintptr_t)&shared->guest_tls_a[0];
    uintptr_t guest_b = (uintptr_t)&shared->guest_tls_b[0];
    if (!child_ok || shared->initial_set_return != guest_a ||
        shared->before_signal_gs0 != TLS_MARKER_A ||
        shared->handler_entered != 1u ||
        shared->handler_instruction_ok != 1u ||
        shared->handler_gs0 != TLS_MARKER_A ||
        shared->handler_set_b_return != guest_b ||
        shared->after_signal_gs0 != TLS_MARKER_B) {
        if (WIFSIGNALED(child_status)) {
            fprintf(stderr, "HRT M2 probe: child terminated by signal %d\n",
                    WTERMSIG(child_status));
        } else if (WIFEXITED(child_status)) {
            fprintf(stderr, "HRT M2 probe: child exited with status %d\n",
                    WEXITSTATUS(child_status));
        }
        fprintf(stderr, "HRT M2 probe: persistent guest GS update failed\n");
        return 2;
    }

    puts("HRT M2 probe: guest GS updates persist through SIGILL under Rosetta");
    return 0;
}
