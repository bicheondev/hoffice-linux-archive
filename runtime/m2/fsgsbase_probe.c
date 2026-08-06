#define _DARWIN_C_SOURCE 1
#include <inttypes.h>
#include <setjmp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

int main(void) {
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    sigemptyset(&action.sa_mask);
    action.sa_handler = illegal_instruction;
    if (sigaction(SIGILL, &action, NULL) != 0) {
        perror("sigaction");
        return 1;
    }

    if (sigsetjmp(g_recovery, 1) != 0) {
        fprintf(stderr, "HRT M2 probe: FSGSBASE instruction trapped\n");
        return 77;
    }

    uintptr_t original = read_fs_base();
    uint64_t *tls = aligned_alloc(64u, 64u);
    if (tls == NULL) {
        perror("aligned_alloc");
        return 1;
    }
    memset(tls, 0, 64u);
    tls[0] = UINT64_C(0x4852544d32544c53); /* HRTM2TLS */

    write_fs_base((uintptr_t)tls);
    uint64_t observed = read_fs_zero();
    write_fs_base(original);

    printf("HRT M2 probe: original-fs=0x%" PRIxPTR
           " requested-fs=%p observed=0x%016" PRIx64 "\n",
           original, (void *)tls, observed);
    free(tls);

    if (g_trapped || observed != UINT64_C(0x4852544d32544c53)) {
        fprintf(stderr, "HRT M2 probe: direct FS-base control failed\n");
        return 2;
    }
    puts("HRT M2 probe: direct FS-base control works under Rosetta");
    return 0;
}
