#include "clone_trampoline.h"

.text
.p2align 4, 0x90
.globl _hrt_m10_enter_clone_child
_hrt_m10_enter_clone_child:
    /* RDI is the host-side HrtM10CloneContext pointer. */
    movq %rdi, %r11

    /* Restore the parent's floating-point and vector state first. */
    fxrstor64 HRT_M10_CLONE_FXSAVE_OFFSET(%r11)

    /* Switch to the Linux-provided child stack. */
    movq HRT_M10_CLONE_RSP_OFFSET(%r11), %rsp
    pushq HRT_M10_CLONE_RIP_OFFSET(%r11)
    pushq HRT_M10_CLONE_RFLAGS_OFFSET(%r11)
    popfq

    movq HRT_M10_CLONE_RBX_OFFSET(%r11), %rbx
    movq HRT_M10_CLONE_RBP_OFFSET(%r11), %rbp
    movq HRT_M10_CLONE_R12_OFFSET(%r11), %r12
    movq HRT_M10_CLONE_R13_OFFSET(%r11), %r13
    movq HRT_M10_CLONE_R14_OFFSET(%r11), %r14
    movq HRT_M10_CLONE_R15_OFFSET(%r11), %r15
    movq HRT_M10_CLONE_R10_OFFSET(%r11), %r10
    movq HRT_M10_CLONE_R8_OFFSET(%r11), %r8
    movq HRT_M10_CLONE_R9_OFFSET(%r11), %r9
    movq HRT_M10_CLONE_RDI_OFFSET(%r11), %rdi
    movq HRT_M10_CLONE_RSI_OFFSET(%r11), %rsi
    movq HRT_M10_CLONE_RDX_OFFSET(%r11), %rdx

    /* clone returns zero in the child; RCX and R11 are syscall-clobbered. */
    xorl %eax, %eax
    retq
