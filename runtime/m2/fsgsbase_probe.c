#define _DARWIN_C_SOURCE 1
#include <inttypes.h>
#include <mach/i386/thread_status.h>
#include <mach/mach.h>
#include <pthread.h>
#include <setjmp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DARWIN_THREAD_FAST_SET_CTHREAD_SELF UINT64_C(0x03000003)
#define TLS_MARKER UINT64_C(0x4852544d32544c53) /* HRTM2TLS */

static sigjmp_buf g_recovery;
static volatile sig_atomic_t g_trapped;

static void illegal_instruction(int signo) {
    (void)signo;
    g_trapped = 1;
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

static uint64_t switch_gs_read_and_restore(uintptr_t guest_base,
                                           uintptr_t host_base) {
    uint64_t observed;
    __asm__ volatile(
        "movq %[guest], %%rdi\n\t"
        "movq %[trap], %%rax\n\t"
        "syscall\n\t"
        "movq %%gs:0, %%r8\n\t"
        "movq %[host], %%rdi\n\t"
        "movq %[trap], %%rax\n\t"
        "syscall\n\t"
        "movq %%r8, %[observed]\n\t"
        : [observed] "=r"(observed)
        : [guest] "r"(guest_base), [host] "r"(host_base),
          [trap] "i"(DARWIN_THREAD_FAST_SET_CTHREAD_SELF)
        : "rax", "rdi", "rcx", "r8", "r11", "cc", "memory");
    return observed;
}

static uintptr_t query_gs_base(void) {
#if defined(x86_THREAD_FULL_STATE64) && defined(x86_THREAD_FULL_STATE64_COUNT)
    x86_thread_full_state64_t state;
    mach_msg_type_number_t count = x86_THREAD_FULL_STATE64_COUNT;
    memset(&state, 0, sizeof(state));
    kern_return_t result = thread_get_state(
        mach_thread_self(), x86_THREAD_FULL_STATE64,
        (thread_state_t)&state, &count);
    if (result == KERN_SUCCESS) return (uintptr_t)state.__gsbase;
#endif
    return (uintptr_t)pthread_self();
}

int main(void) {
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    sigemptyset(&action.sa_mask);
    action.sa_handler = illegal_instruction;
    if (sigaction(SIGILL, &action, NULL) != 0) {
        perror("sigaction");
        return 1;
    }

    int direct_fs_supported = 0;
    uintptr_t original_fs = 0;
    if (sigsetjmp(g_recovery, 1) == 0) {
        original_fs = read_fs_base();
        uint64_t fs_test = TLS_MARKER;
        write_fs_base((uintptr_t)&fs_test);
        direct_fs_supported = read_fs_zero() == TLS_MARKER;
        write_fs_base(original_fs);
    }

    uint64_t original_gs_zero = read_gs_zero();
    uintptr_t host_gs_base = query_gs_base();
    uint64_t *guest_tls = aligned_alloc(64u, 64u);
    if (guest_tls == NULL) {
        perror("aligned_alloc");
        return 1;
    }
    memset(guest_tls, 0, 64u);
    guest_tls[0] = TLS_MARKER;

    uint64_t observed = switch_gs_read_and_restore(
        (uintptr_t)guest_tls, host_gs_base);
    uint64_t restored_gs_zero = read_gs_zero();

    printf("HRT M2 probe: direct-fs=%s original-fs=0x%" PRIxPTR "\n",
           direct_fs_supported ? "yes" : "no", original_fs);
    printf("HRT M2 probe: host-gs-base=0x%" PRIxPTR
           " original-gs0=0x%016" PRIx64
           " restored-gs0=0x%016" PRIx64 "\n",
           host_gs_base, original_gs_zero, restored_gs_zero);
    printf("HRT M2 probe: guest-gs=%p observed=0x%016" PRIx64 "\n",
           (void *)guest_tls, observed);
    free(guest_tls);

    if (observed != TLS_MARKER || restored_gs_zero != original_gs_zero) {
        fprintf(stderr, "HRT M2 probe: GS TLS fallback failed\n");
        return 2;
    }
    puts("HRT M2 probe: GS TLS fallback works under Rosetta");
    return 0;
}
