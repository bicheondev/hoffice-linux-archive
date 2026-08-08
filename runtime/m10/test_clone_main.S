.section .text
.p2align 4
.globl _start
.hidden _start
.type _start,@function
_start:
    /* Verify guest-root-confined chdir and getcwd first. */
    movq $80, %rax
    leaq .Ldirectory(%rip), %rdi
    syscall
    testq %rax, %rax
    js .Lfailure

    movq $79, %rax
    leaq .Lcwd_buffer(%rip), %rdi
    movq $256, %rsi
    syscall
    testq %rax, %rax
    jle .Lfailure
    movq %rax, %r12

    movq $1, %rax
    movq $1, %rdi
    leaq .Lcwd_prefix(%rip), %rsi
    movq $(.Lcwd_prefix_end-.Lcwd_prefix), %rdx
    syscall
    movq $1, %rax
    movq $1, %rdi
    leaq .Lcwd_buffer(%rip), %rsi
    leaq -1(%r12), %rdx
    syscall
    movq $1, %rax
    movq $1, %rdi
    leaq .Lnewline(%rip), %rsi
    movq $1, %rdx
    syscall

    /*
     * The exact NPTL flag set observed in HWord:
     * VM|FS|FILES|SIGHAND|THREAD|SYSVSEM|SETTLS|PARENT_SETTID|
     * CHILD_CLEARTID = 0x3d0f00.
     */
    movq $56, %rax
    movq $0x3d0f00, %rdi
    leaq .Lchild_stack_end(%rip), %rsi
    andq $-16, %rsi
    leaq .Ltid_word(%rip), %rdx
    leaq .Ltid_word(%rip), %r10
    leaq .Ltls_block(%rip), %r8
    xorq %r9, %r9
    syscall
    testq %rax, %rax
    js .Lfailure
    jz .Lchild

    /* Parent waits for CLONE_CHILD_CLEARTID to become zero. */
    movq $500000000, %rcx
.Lwait_for_child:
    cmpl $0, .Ltid_word(%rip)
    je .Lparent_complete
    pause
    decq %rcx
    jne .Lwait_for_child
    jmp .Lfailure

.Lparent_complete:
    movq $1, %rax
    movq $1, %rdi
    leaq .Lparent_message(%rip), %rsi
    movq $(.Lparent_message_end-.Lparent_message), %rdx
    syscall
    movq $231, %rax
    xorq %rdi, %rdi
    syscall
    ud2

.Lchild:
    movq $1, %rax
    movq $1, %rdi
    leaq .Lchild_message(%rip), %rsi
    movq $(.Lchild_message_end-.Lchild_message), %rdx
    syscall
    movq $60, %rax
    xorq %rdi, %rdi
    syscall
    ud2

.Lfailure:
    movq $1, %rax
    movq $2, %rdi
    leaq .Lfailure_message(%rip), %rsi
    movq $(.Lfailure_message_end-.Lfailure_message), %rdx
    syscall
    movq $231, %rax
    movq $111, %rdi
    syscall
    ud2
.size _start,.-_start

.section .rodata
.Ldirectory:
    .asciz "/opt/hrt/subdir"
.Lcwd_prefix:
    .ascii "HRT M10 CLONE GUEST: cwd="
.Lcwd_prefix_end:
.Lnewline:
    .ascii "\n"
.Lchild_message:
    .ascii "HRT M10 CLONE GUEST: child resumed and exited\n"
.Lchild_message_end:
.Lparent_message:
    .ascii "HRT M10 CLONE GUEST: parent observed CHILD_CLEARTID\n"
.Lparent_message_end:
.Lfailure_message:
    .ascii "HRT M10 CLONE GUEST: failure\n"
.Lfailure_message_end:

.section .bss
.p2align 4
.Ltid_word:
    .zero 8
.p2align 4
.Ltls_block:
    .zero 4096
.p2align 4
.Lcwd_buffer:
    .zero 256
.p2align 4
.Lchild_stack:
    .zero 1048576
.Lchild_stack_end:
