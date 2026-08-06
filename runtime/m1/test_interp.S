.section .text
.globl _start
.type _start,@function
_start:
    xorq %rbp, %rbp
    movq %rsp, %r12

    movq $1, %rax
    movq $1, %rdi
    leaq interp_message(%rip), %rsi
    movq $(interp_message_end-interp_message), %rdx
    syscall

    movq (%r12), %rcx
    leaq 16(%r12,%rcx,8), %r13
1:
    movq (%r13), %rax
    addq $8, %r13
    testq %rax, %rax
    jne 1b
2:
    movq (%r13), %rax
    movq 8(%r13), %r14
    cmpq $9, %rax
    je 3f
    testq %rax, %rax
    je 4f
    addq $16, %r13
    jmp 2b
3:
    xorq %rdx, %rdx
    movq %r12, %rsp
    jmp *%r14
4:
    movq $60, %rax
    movq $111, %rdi
    syscall
.size _start, .-_start

.section .rodata
interp_message:
    .ascii "HRT M1: PT_INTERP entered\n"
interp_message_end:

.section .note.GNU-stack,"",@progbits
