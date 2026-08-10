.section .text
.globl _start
.type _start,@function
_start:
    xorq %rbp, %rbp

    /* Linux arch_prctl(ARCH_SET_FS, tls_a). */
    leaq tls_a(%rip), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jne fail_set_a

    /* The host rewrites this Linux FS prefix to guest GS. */
    movq %fs:0, %r12
    movabsq $0x4852544d32544c41, %r13
    cmpq %r13, %r12
    jne fail_read_a

    /* Linux arch_prctl(ARCH_GET_FS, &fs_slot). */
    leaq fs_slot(%rip), %rsi
    movq $0x1003, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jne fail_get
    movq fs_slot(%rip), %r14
    leaq tls_a(%rip), %r15
    cmpq %r15, %r14
    jne fail_get

    /* Change the guest TLS base from inside the SIGILL syscall bridge. */
    leaq tls_b(%rip), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jne fail_set_b

    movq %fs:0, %r12
    movabsq $0x4852544d32544c42, %r13
    cmpq %r13, %r12
    jne fail_read_b

    movq $39, %rax
    syscall
    testq %rax, %rax
    jle fail_getpid

    movq $1, %rax
    movq $1, %rdi
    movq success_pointer(%rip), %rsi
    movq $(success_end-success_message), %rdx
    syscall
    testq %rax, %rax
    js fail_write

    movq $60, %rax
    xorq %rdi, %rdi
    syscall

fail_set_a:
    movq $71, %rdi
    jmp fail_exit
fail_read_a:
    movq $72, %rdi
    jmp fail_exit
fail_get:
    movq $73, %rdi
    jmp fail_exit
fail_set_b:
    movq $74, %rdi
    jmp fail_exit
fail_read_b:
    movq $75, %rdi
    jmp fail_exit
fail_getpid:
    movq $76, %rdi
    jmp fail_exit
fail_write:
    movq $77, %rdi
fail_exit:
    movq $60, %rax
    syscall
.size _start, .-_start

.section .rodata
success_message:
    .ascii "HRT M2: arch_prctl SET/GET and rewritten FS TLS passed\n"
success_end:

.section .data
.p2align 6
tls_a:
    .quad 0x4852544d32544c41
    .zero 56
.p2align 6
tls_b:
    .quad 0x4852544d32544c42
    .zero 56
.p2align 3
fs_slot:
    .quad 0
success_pointer:
    .quad success_message

.section .note.GNU-stack,"",@progbits
