.text
.p2align 4, 0x90
.globl _hrt_m6_deferred_hostcall_entry
_hrt_m6_deferred_hostcall_entry:
    fxsave64 _g_hrt_m6_pending+192(%rip)
    leaq _g_hrt_m6_pending(%rip), %rdi
    callq _hrt_m6_execute_hostcall
    ud2

.p2align 4, 0x90
.globl _hrt_m6_resume_guest
_hrt_m6_resume_guest:
    movq %rdi, %r15

    fxrstor64 192(%r15)

    /* Restore the guest GS base after all Objective-C and libc work. */
    movq 56(%r15), %rdi
    movq $0x03000003, %rax
    syscall

    /* Use the original guest stack and leave its pointer unchanged after ret. */
    movq 80(%r15), %rsp
    pushq 64(%r15)
    pushq 72(%r15)
    popfq

    movq 88(%r15), %rbx
    movq 96(%r15), %rbp
    movq 104(%r15), %r12
    movq 112(%r15), %r13
    movq 120(%r15), %r14

    movq 136(%r15), %rdi
    movq 144(%r15), %rsi
    movq 152(%r15), %rdx
    movq 160(%r15), %r10
    movq 168(%r15), %r8
    movq 176(%r15), %r9

    movq 184(%r15), %rax
    movq 64(%r15), %rcx
    movq 72(%r15), %r11
    movq 128(%r15), %r15
    retq
