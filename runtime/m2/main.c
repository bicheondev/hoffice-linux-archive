#include "hrt_m2.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void usage(const char *program) {
    fprintf(stderr, "usage: %s --root /host/rootfs --program /guest/program\n",
            program);
}

int main(int argc, char **argv) {
    if (argc != 5 || strcmp(argv[1], "--root") != 0 ||
        strcmp(argv[3], "--program") != 0) {
        usage(argv[0]);
        return 64;
    }

    const char *root = argv[2];
    const char *guest_program = argv[4];
    char program_path[HRT_MAX_PATH];
    resolve_guest_path(root, guest_program,
                       program_path, sizeof(program_path));

    g_page_size = (size_t)getpagesize();
    install_sigill_handler();

    LoadedElf program = load_elf(program_path);
    if (program.interp_path[0] == '\0') {
        errno = 0;
        fatal("M2 program does not contain PT_INTERP");
    }

    char interpreter_path[HRT_MAX_PATH];
    resolve_guest_path(root, program.interp_path,
                       interpreter_path, sizeof(interpreter_path));
    LoadedElf interpreter = load_elf(interpreter_path);
    if (interpreter.interp_path[0] != '\0') {
        errno = 0;
        fatal("nested PT_INTERP is not supported");
    }

    size_t program_fs_prefixes = rewrite_linux_fs_to_gs(&program);
    size_t interpreter_fs_prefixes = rewrite_linux_fs_to_gs(&interpreter);
    if (program_fs_prefixes == 0u) {
        errno = 0;
        fatal("M2 proof program contains no recognized Linux FS accesses");
    }

    fprintf(stderr,
            "hrt-m2: program image=[%p,%p) bias=%p entry=%p "
            "relocations=%zu syscalls=%zu fs-prefixes=%zu interp=%s\n",
            (void *)program.image_start, (void *)program.image_end,
            (void *)program.load_bias, (void *)program.entry_address,
            program.applied_relocations, program.patched_syscalls,
            program_fs_prefixes, program.interp_path);
    fprintf(stderr,
            "hrt-m2: interpreter image=[%p,%p) base=%p entry=%p "
            "relocations=%zu syscalls=%zu fs-prefixes=%zu\n",
            (void *)interpreter.image_start, (void *)interpreter.image_end,
            (void *)interpreter.load_bias,
            (void *)interpreter.entry_address,
            interpreter.applied_relocations, interpreter.patched_syscalls,
            interpreter_fs_prefixes);

    if (program.patched_syscalls == 0u ||
        interpreter.patched_syscalls == 0u) {
        errno = 0;
        fatal("M2 proof images must contain Linux syscall instructions");
    }

    void *stack_pointer = build_initial_stack(
        guest_program, &program, &interpreter);
    enter_guest(stack_pointer, (void *)interpreter.entry_address);
}
