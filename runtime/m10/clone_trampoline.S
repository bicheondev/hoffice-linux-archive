#include "clone_trampoline.h"

.text
.p2align 4, 0x90
.globl _hrt_m10_enter_clone_child
_hrt_m10_enter_clone_child:
    /*
     * Enter this leaf while the new pthread still owns its normal host GS.
     * Save every Darwin x86-64 callee-saved register, the call-entry stack and
     * the host floating-point/vector image before any Linux state is applied.
     * The exit trampoline restores this complete ABI frame and returns to the
     * ordinary pthread start callback; no pthread cleanup runs on guest memory.
     */
    movq %rsp, HRT_M10_CLONE_HOST_RSP_OFFSET(%rdi)
    movq %rbp, HRT_M10_CLONE_HOST_RBP_OFFSET(%rdi)
    movq %rbx, HRT_M10_CLONE_HOST_RBX_OFFSET(%rdi)
    movq %r12, HRT_M10_CLONE_HOST_R12_OFFSET(%rdi)
    movq %r13, HRT_M10_CLONE_HOST_R13_OFFSET(%rdi)
    movq %r14, HRT_M10_CLONE_HOST_R14_OFFSET(%rdi)
    movq %r15, HRT_M10_CLONE_HOST_R15_OFFSET(%rdi)
    fxsave64 HRT_M10_CLONE_HOST_FXSAVE_OFFSET(%rdi)
    movq %rdi, %r12

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_enter(%rip), %rsi
    movq $(.Lclone_trace_enter_end-.Lclone_trace_enter), %rdx
    syscall

    /* The Linux clone TLS argument is the guest R8 value. */
    movq HRT_M10_CLONE_R8_OFFSET(%r12), %rdi
    movq %rdi, HRT_M10_THREAD_GUEST_GS_OFFSET(%r12)
    movabsq $0x03000003, %rax
    syscall

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_gs(%rip), %rsi
    movq $(.Lclone_trace_gs_end-.Lclone_trace_gs), %rdx
    syscall

    /* Restore the Linux parent's floating-point and vector state. */
    fxrstor64 HRT_M10_CLONE_FXSAVE_OFFSET(%r12)

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_fx(%rip), %rsi
    movq $(.Lclone_trace_fx_end-.Lclone_trace_fx), %rdx
    syscall

    /* Linux clone resumes after syscall with the supplied child stack. */
    movq HRT_M10_CLONE_RSP_OFFSET(%r12), %rsp
    pushq HRT_M10_CLONE_RFLAGS_OFFSET(%r12)
    popfq

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_stack(%rip), %rsi
    movq $(.Lclone_trace_stack_end-.Lclone_trace_stack), %rdx
    syscall

    movq HRT_M10_CLONE_RIP_OFFSET(%r12), %r11
    movq HRT_M10_CLONE_RBX_OFFSET(%r12), %rbx
    movq HRT_M10_CLONE_RBP_OFFSET(%r12), %rbp
    movq HRT_M10_CLONE_R13_OFFSET(%r12), %r13
    movq HRT_M10_CLONE_R14_OFFSET(%r12), %r14
    movq HRT_M10_CLONE_R15_OFFSET(%r12), %r15
    movq HRT_M10_CLONE_R10_OFFSET(%r12), %r10
    movq HRT_M10_CLONE_R8_OFFSET(%r12), %r8
    movq HRT_M10_CLONE_R9_OFFSET(%r12), %r9
    movq HRT_M10_CLONE_RDI_OFFSET(%r12), %rdi
    movq HRT_M10_CLONE_RSI_OFFSET(%r12), %rsi
    movq HRT_M10_CLONE_RDX_OFFSET(%r12), %rdx
    movq HRT_M10_CLONE_R12_OFFSET(%r12), %r12

    /* clone returns zero in the child; RCX and R11 are syscall-clobbered. */
    xorl %eax, %eax
    jmpq *%r11

.p2align 4, 0x90
.globl _hrt_m10_exit_clone_child
_hrt_m10_exit_clone_child:
    /*
     * RDI=context and RSI=Linux exit status.  Signal return enters here with
     * guest GS and an arbitrary guest/alternate stack.  Restore host TLS and
     * the complete original call frame, then return normally from
     * hrt_m10_enter_clone_child into m10_clone_thread_start.
     */
    movq %rdi, %r12
    movq %rsi, HRT_M10_CLONE_EXIT_STATUS_OFFSET(%r12)
    movq HRT_M10_THREAD_HOST_GS_OFFSET(%r12), %rdi
    movabsq $0x03000003, %rax
    syscall

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_exit_stack(%rip), %rsi
    movq $(.Lclone_trace_exit_stack_end-.Lclone_trace_exit_stack), %rdx
    syscall

    fxrstor64 HRT_M10_CLONE_HOST_FXSAVE_OFFSET(%r12)
    movq HRT_M10_CLONE_HOST_RSP_OFFSET(%r12), %rsp
    movq HRT_M10_CLONE_HOST_RBP_OFFSET(%r12), %rbp
    movq HRT_M10_CLONE_HOST_RBX_OFFSET(%r12), %rbx
    movq HRT_M10_CLONE_HOST_R13_OFFSET(%r12), %r13
    movq HRT_M10_CLONE_HOST_R14_OFFSET(%r12), %r14
    movq HRT_M10_CLONE_HOST_R15_OFFSET(%r12), %r15
    movq HRT_M10_CLONE_HOST_R12_OFFSET(%r12), %r12
    xorl %eax, %eax
    retq

.section __TEXT,__const
.Lclone_trace_enter:
    .ascii "HRT M10 CLONE ASM: enter\n"
.Lclone_trace_enter_end:
.Lclone_trace_gs:
    .ascii "HRT M10 CLONE ASM: guest-gs-set\n"
.Lclone_trace_gs_end:
.Lclone_trace_fx:
    .ascii "HRT M10 CLONE ASM: fx-restored\n"
.Lclone_trace_fx_end:
.Lclone_trace_stack:
    .ascii "HRT M10 CLONE ASM: guest-stack-ready\n"
.Lclone_trace_stack_end:
.Lclone_trace_exit_stack:
    .ascii "HRT M10 CLONE ASM: host-return-frame-ready\n"
.Lclone_trace_exit_stack_end:
