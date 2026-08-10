.section .bss
.p2align 4
.Ltls_block:
    .zero 32

.section .text
.p2align 4
.globl _start
.hidden _start
.type _start,@function
_start:
    movq %rsp, %r12
    leaq .Ltls_block(%rip), %r13
    movq %r13, 0(%r13)
    movq $0x4852544d32544c53, %rax
    movq %rax, 8(%r13)

    movq $158, %rax
    movq $0x1002, %rdi
    movq %r13, %rsi
    syscall
    testq %rax, %rax
    jne .Lfailure

    movq %fs:0, %rax
    cmpq %r13, %rax
    jne .Lfailure
    movq %fs:8, %rax
    movabsq $0x4852544d32544c53, %r14
    cmpq %r14, %rax
    jne .Lfailure

    movq $39, %rax
    syscall
    testq %rax, %rax
    jle .Lfailure

    movq %fs:0, %rax
    cmpq %r13, %rax
    jne .Lfailure
    movq %fs:8, %rax
    cmpq %r14, %rax
    jne .Lfailure

    movq $1, %rax
    movq $1, %rdi
    leaq .Lsuccess_message(%rip), %rsi
    movq $(.Lsuccess_message_end-.Lsuccess_message), %rdx
    syscall

    movq %r12, %rsp
    movq (%rsp), %rcx
    leaq 8(%rsp), %r8
    leaq 8(%r8,%rcx,8), %r8
.Lskip_environment:
    movq (%r8), %rax
    addq $8, %r8
    testq %rax, %rax
    jne .Lskip_environment
.Lscan_auxv:
    movq (%r8), %rax
    movq 8(%r8), %rdx
    addq $16, %r8
    testq %rax, %rax
    je .Lfailure
    cmpq $9, %rax
    jne .Lscan_auxv
    jmp *%rdx

.Lfailure:
    movq $1, %rax
    movq $2, %rdi
    leaq .Lfailure_message(%rip), %rsi
    movq $(.Lfailure_message_end-.Lfailure_message), %rdx
    syscall
    movq $60, %rax
    movq $112, %rdi
    syscall
    ud2
.size _start,.-_start

.section .rodata
.Lsuccess_message:
    .ascii "HRT M2 TLS: ARCH_SET_FS survived signal-return and another syscall\n"
.Lsuccess_message_end:
.Lfailure_message:
    .ascii "HRT M2 TLS: FS-base persistence test failed\n"
.Lfailure_message_end:
