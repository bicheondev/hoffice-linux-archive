.section .rodata
message:
    .ascii "HRT M0: Linux ELF executed through the macOS syscall bridge\n"
.set message_length, . - message

.section .text
.global _start
.type _start,@function
_start:
    mov $1, %rax
    mov $1, %rdi
    lea message(%rip), %rsi
    mov $message_length, %rdx
    syscall

    mov $39, %rax
    syscall

    mov $60, %rax
    xor %rdi, %rdi
    syscall
.size _start, . - _start
