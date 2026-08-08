#include "clone_trampoline.h"

.text
.p2align 4, 0x90
.globl _hrt_m10_enter_clone_child
_hrt_m10_enter_clone_child:
    /*
     * Enter this leaf while the new pthread still owns its normal host GS.
     * Calling a Mach-O symbol for the first time after changing GS can enter
     * dyld or pthread code that expects host TLS.  Keep the context in R12,
     * enter the already-bound assembly symbol first, and perform the raw
     * Darwin SET_GS syscall here with no intervening C runtime operation.
     */
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

    /* Restore the parent's floating-point and vector state. */
    fxrstor64 HRT_M10_CLONE_FXSAVE_OFFSET(%r12)

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_fx(%rip), %rsi
    movq $(.Lclone_trace_fx_end-.Lclone_trace_fx), %rdx
    syscall

    /*
     * Linux clone resumes at the instruction following syscall with RSP equal
     * to the supplied child stack.  Jump directly instead of manufacturing a
     * host return address on guest memory; this also prevents a diagnostic
     * Darwin syscall from touching the continuation word through Rosetta's
     * translated call machinery.
     */
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
