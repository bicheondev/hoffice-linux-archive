#ifndef HRT_M10_CLONE_TRAMPOLINE_H
#define HRT_M10_CLONE_TRAMPOLINE_H

#define HRT_M10_THREAD_ACTIVE_OFFSET 0
#define HRT_M10_THREAD_READY_OFFSET 8
#define HRT_M10_THREAD_TID_OFFSET 16
#define HRT_M10_THREAD_IN_HANDLER_OFFSET 24
#define HRT_M10_THREAD_HOST_GS_OFFSET 32
#define HRT_M10_THREAD_GUEST_GS_OFFSET 40
#define HRT_M10_THREAD_TLS_ACTIVE_OFFSET 48
#define HRT_M10_THREAD_CLEAR_TID_OFFSET 56
#define HRT_M10_THREAD_LAST_SYSCALL_OFFSET 64
#define HRT_M10_THREAD_LAST_RIP_OFFSET 72
#define HRT_M10_CLONE_FLAGS_OFFSET 80
#define HRT_M10_CLONE_RIP_OFFSET 88
#define HRT_M10_CLONE_RSP_OFFSET 96
#define HRT_M10_CLONE_RFLAGS_OFFSET 104
#define HRT_M10_CLONE_RBX_OFFSET 112
#define HRT_M10_CLONE_RBP_OFFSET 120
#define HRT_M10_CLONE_R12_OFFSET 128
#define HRT_M10_CLONE_R13_OFFSET 136
#define HRT_M10_CLONE_R14_OFFSET 144
#define HRT_M10_CLONE_R15_OFFSET 152
#define HRT_M10_CLONE_RDI_OFFSET 160
#define HRT_M10_CLONE_RSI_OFFSET 168
#define HRT_M10_CLONE_RDX_OFFSET 176
#define HRT_M10_CLONE_R10_OFFSET 184
#define HRT_M10_CLONE_R8_OFFSET 192
#define HRT_M10_CLONE_R9_OFFSET 200
#define HRT_M10_CLONE_PARENT_TID_OFFSET 208
#define HRT_M10_CLONE_CHILD_TID_OFFSET 216
#define HRT_M10_CLONE_HOST_THREAD_OFFSET 224
#define HRT_M10_CLONE_RESERVED_OFFSET 232
#define HRT_M10_CLONE_FXSAVE_OFFSET 240
#define HRT_M10_CLONE_FXSAVE_SIZE 512
#define HRT_M10_CLONE_HOST_RSP_OFFSET 752
#define HRT_M10_CLONE_HOST_RBP_OFFSET 760
#define HRT_M10_CLONE_HOST_RBX_OFFSET 768
#define HRT_M10_CLONE_HOST_R12_OFFSET 776
#define HRT_M10_CLONE_HOST_R13_OFFSET 784
#define HRT_M10_CLONE_HOST_R14_OFFSET 792
#define HRT_M10_CLONE_HOST_R15_OFFSET 800
#define HRT_M10_CLONE_EXIT_STATUS_OFFSET 808
#define HRT_M10_CLONE_HOST_FXSAVE_OFFSET 816
#define HRT_M10_CLONE_HOST_FXSAVE_SIZE 512
#define HRT_M10_CLONE_CONTEXT_SIZE 1328

#ifndef __ASSEMBLER__

#include <signal.h>
#include <stddef.h>
#include <stdint.h>

typedef struct __attribute__((aligned(16))) {
    volatile uint64_t active;
    volatile uint64_t ready;
    uint64_t linux_tid;
    volatile uint64_t in_handler;
    uint64_t host_gs;
    uint64_t guest_gs;
    uint64_t guest_tls_active;
    uint64_t clear_child_tid;
    uint64_t last_linux_syscall;
    uint64_t last_linux_syscall_rip;
    uint64_t flags;
    uint64_t resume_rip;
    uint64_t guest_rsp;
    uint64_t guest_rflags;
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
    uint64_t parent_tid_address;
    uint64_t child_tid_address;
    uint64_t host_thread_bits;
    uint64_t reserved;
    unsigned char fxsave[HRT_M10_CLONE_FXSAVE_SIZE]
        __attribute__((aligned(16)));
    uint64_t host_rsp;
    uint64_t host_rbp;
    uint64_t host_rbx;
    uint64_t host_r12;
    uint64_t host_r13;
    uint64_t host_r14;
    uint64_t host_r15;
    uint64_t exit_status;
    unsigned char host_fxsave[HRT_M10_CLONE_HOST_FXSAVE_SIZE]
        __attribute__((aligned(16)));
} HrtM10CloneContext;

_Static_assert(offsetof(HrtM10CloneContext, active) ==
                   HRT_M10_THREAD_ACTIVE_OFFSET,
               "clone active offset");
_Static_assert(offsetof(HrtM10CloneContext, ready) ==
                   HRT_M10_THREAD_READY_OFFSET,
               "clone ready offset");
_Static_assert(offsetof(HrtM10CloneContext, linux_tid) ==
                   HRT_M10_THREAD_TID_OFFSET,
               "clone TID offset");
_Static_assert(offsetof(HrtM10CloneContext, host_gs) ==
                   HRT_M10_THREAD_HOST_GS_OFFSET,
               "clone host GS offset");
_Static_assert(offsetof(HrtM10CloneContext, guest_gs) ==
                   HRT_M10_THREAD_GUEST_GS_OFFSET,
               "clone guest GS offset");
_Static_assert(offsetof(HrtM10CloneContext, resume_rip) ==
                   HRT_M10_CLONE_RIP_OFFSET,
               "clone RIP offset");
_Static_assert(offsetof(HrtM10CloneContext, guest_rsp) ==
                   HRT_M10_CLONE_RSP_OFFSET,
               "clone RSP offset");
_Static_assert(offsetof(HrtM10CloneContext, guest_rbx) ==
                   HRT_M10_CLONE_RBX_OFFSET,
               "clone RBX offset");
_Static_assert(offsetof(HrtM10CloneContext, guest_r9) ==
                   HRT_M10_CLONE_R9_OFFSET,
               "clone R9 offset");
_Static_assert(offsetof(HrtM10CloneContext, fxsave) ==
                   HRT_M10_CLONE_FXSAVE_OFFSET,
               "clone FXSAVE offset");
_Static_assert(offsetof(HrtM10CloneContext, host_rsp) ==
                   HRT_M10_CLONE_HOST_RSP_OFFSET,
               "clone host RSP offset");
_Static_assert(offsetof(HrtM10CloneContext, host_rbp) ==
                   HRT_M10_CLONE_HOST_RBP_OFFSET,
               "clone host RBP offset");
_Static_assert(offsetof(HrtM10CloneContext, host_rbx) ==
                   HRT_M10_CLONE_HOST_RBX_OFFSET,
               "clone host RBX offset");
_Static_assert(offsetof(HrtM10CloneContext, host_r12) ==
                   HRT_M10_CLONE_HOST_R12_OFFSET,
               "clone host R12 offset");
_Static_assert(offsetof(HrtM10CloneContext, host_r13) ==
                   HRT_M10_CLONE_HOST_R13_OFFSET,
               "clone host R13 offset");
_Static_assert(offsetof(HrtM10CloneContext, host_r14) ==
                   HRT_M10_CLONE_HOST_R14_OFFSET,
               "clone host R14 offset");
_Static_assert(offsetof(HrtM10CloneContext, host_r15) ==
                   HRT_M10_CLONE_HOST_R15_OFFSET,
               "clone host R15 offset");
_Static_assert(offsetof(HrtM10CloneContext, exit_status) ==
                   HRT_M10_CLONE_EXIT_STATUS_OFFSET,
               "clone exit status offset");
_Static_assert(offsetof(HrtM10CloneContext, host_fxsave) ==
                   HRT_M10_CLONE_HOST_FXSAVE_OFFSET,
               "clone host FXSAVE offset");
_Static_assert(sizeof(HrtM10CloneContext) == HRT_M10_CLONE_CONTEXT_SIZE,
               "clone context size");

#ifdef __cplusplus
extern "C" {
#endif

void hrt_m10_enter_clone_child(HrtM10CloneContext *context);
void hrt_m10_exit_clone_child(HrtM10CloneContext *context, int status)
    __attribute__((noreturn));

#ifdef __cplusplus
}
#endif

#endif /* !__ASSEMBLER__ */

#endif
