#include "clone_trampoline.h"

.text
.p2align 4, 0x90
.globl _hrt_m10_enter_clone_child
_hrt_m10_enter_clone_child:
    /*
     * RDI is the host-side HrtM10CloneContext pointer.  Darwin syscall
     * clobbers R11, so keep the context in R12 until the guest R12 value is
     * restored.  The three raw-write markers are diagnostic and avoid libc,
     * allocation, Mach-O TLS and the Linux syscall trap.
     */
    movq %rdi, %r12

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_enter(%rip), %rsi
    movq $(.Lclone_trace_enter_end-.Lclone_trace_enter), %rdx
    syscall

    /* Restore the parent's floating-point and vector state first. */
    fxrstor64 HRT_M10_CLONE_FXSAVE_OFFSET(%r12)

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_fx(%rip), %rsi
    movq $(.Lclone_trace_fx_end-.Lclone_trace_fx), %rdx
    syscall

    /* Switch to the Linux-provided child stack. */
    movq HRT_M10_CLONE_RSP_OFFSET(%r12), %rsp
    pushq HRT_M10_CLONE_RIP_OFFSET(%r12)
    pushq HRT_M10_CLONE_RFLAGS_OFFSET(%r12)
    popfq

    movabsq $0x2000004, %rax
    movq $2, %rdi
    leaq .Lclone_trace_stack(%rip), %rsi
    movq $(.Lclone_trace_stack_end-.Lclone_trace_stack), %rdx
    syscall

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
    retq

.section __TEXT,__cstring,cstring_literals
.Lclone_trace_enter:
    .ascii "HRT M10 CLONE ASM: enter\n"
.Lclone_trace_enter_end:
.Lclone_trace_fx:
    .ascii "HRT M10 CLONE ASM: fx-restored\n"
.Lclone_trace_fx_end:
.Lclone_trace_stack:
    .ascii "HRT M10 CLONE ASM: guest-stack-ready\n"
.Lclone_trace_stack_end:
