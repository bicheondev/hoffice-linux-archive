.text
.globl _enter_guest
.p2align 4, 0x90
_enter_guest:
    movq %rdi, %rsp
    xorq %rbp, %rbp
    jmp *%rsi
