.text
.p2align 4, 0x90
.globl _hrt_set_fs_trampoline
_hrt_set_fs_trampoline:
    wrfsbase %rdi
    xorq %rax, %rax
    jmp *%r11
