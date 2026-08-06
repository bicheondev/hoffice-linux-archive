.section .text
.globl _start
.type _start,@function
_start:
    xorq %rbp, %rbp
    movq $1, %rax
    movq $1, %rdi
    movq message_pointer(%rip), %rsi
    movq $(message_end-message), %rdx
    syscall
    movq $60, %rax
    xorq %rdi, %rdi
    syscall
.size _start, .-_start

.section .rodata
message:
    .ascii "HRT M1: relocated PIE main entered\n"
message_end:

.section .data
.p2align 3
message_pointer:
    .quad message

.section .note.GNU-stack,"",@progbits
