#ifndef HRT_M6_HOSTCALL_TRAMPOLINE_H
#define HRT_M6_HOSTCALL_TRAMPOLINE_H

#include <stdint.h>

#define HRT_M6_HOSTCALL_STACK_SIZE (1024u * 1024u)
#define HRT_M6_FXSAVE_SIZE 512u

typedef struct __attribute__((aligned(16))) {
    uint64_t active;
    uint64_t opcode;
    uint64_t argument1;
    uint64_t argument2;
    uint64_t argument3;
    uint64_t argument4;
    uint64_t argument5;
    uint64_t guest_gs_base;
    uint64_t resume_rip;
    uint64_t resume_rflags;
    uint64_t guest_rsp;
    uint64_t guest_rbx;
    uint64_t guest_rbp;
    uint64_t guest_r12;
    uint64_t guest_r13;
    uint64_t guest_r14;
    uint64_t guest_r15;
    uint64_t guest_rdi;
    uint64_t guest_rsi;
    uint64_t guest_rdx;
    uint64_t guest_r10;
    uint64_t guest_r8;
    uint64_t guest_r9;
    int64_t result;
    unsigned char fxsave[HRT_M6_FXSAVE_SIZE] __attribute__((aligned(16)));
} HrtM6PendingHostcall;

#ifdef __cplusplus
extern "C" {
#endif

extern HrtM6PendingHostcall g_hrt_m6_pending;
extern unsigned char g_hrt_m6_hostcall_stack[HRT_M6_HOSTCALL_STACK_SIZE];

void hrt_m6_deferred_hostcall_entry(void) __attribute__((noreturn));
void hrt_m6_execute_hostcall(HrtM6PendingHostcall *pending)
    __attribute__((noreturn));
void hrt_m6_resume_guest(HrtM6PendingHostcall *pending)
    __attribute__((noreturn));

#ifdef __cplusplus
}
#endif

#endif
