.text
.p2align 4, 0x90
.globl _enter_guest
_enter_guest:
    movq %rsi, %rax
    movq %rdi, %rsp
    xorq %rbp, %rbp
    xorq %rdx, %rdx
    jmp *%rax
