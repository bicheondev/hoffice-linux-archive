#include "appkit_adapter.h"
#include "hrt_m3.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void usage(const char *program) {
    fprintf(stderr,
            "usage: %s --root /host/rootfs --program /guest/program\n",
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

    char prepatch_marker[HRT_MAX_PATH];
    resolve_guest_path(root, "/.hrt-prepatched-v1",
                       prepatch_marker, sizeof(prepatch_marker));
    if (access(prepatch_marker, R_OK) == 0) {
        set_prepatched_code_mode(1);
        fprintf(stderr,
                "hrt-m6: verified instruction-boundary guest root enabled\n");
    }

    int appkit_result = hrt_m6_appkit_initialize();
    if (appkit_result != 0) {
        errno = 0;
        fprintf(stderr,
                "hrt-m6: AppKit initialization failed with result %d\n",
                appkit_result);
        return 70;
    }

    g_page_size = (size_t)getpagesize();
    initialize_syscall_bridge(root, guest_program);

    LoadedElf program = load_unrelocated_elf(program_path);
    if (program.interp_path[0] == '\0') {
        errno = 0;
        fatal("M6 guest does not contain PT_INTERP");
    }

    char interpreter_path[HRT_MAX_PATH];
    resolve_guest_path(root, program.interp_path,
                       interpreter_path, sizeof(interpreter_path));
    LoadedElf interpreter = load_unrelocated_elf(interpreter_path);
    if (interpreter.interp_path[0] != '\0') {
        errno = 0;
        fatal("M6 nested PT_INTERP is not supported");
    }

    size_t program_fs = 0u;
    size_t interpreter_fs = 0u;
    (void)patch_loaded_elf(&program, &program_fs);
    (void)patch_loaded_elf(&interpreter, &interpreter_fs);

    fprintf(stderr,
            "hrt-m6: program image=[%p,%p) bias=%p entry=%p "
            "syscalls=%zu fs-prefixes=%zu interp=%s\n",
            (void *)program.image_start, (void *)program.image_end,
            (void *)program.load_bias, (void *)program.entry_address,
            program.patched_syscalls, program_fs, program.interp_path);
    fprintf(stderr,
            "hrt-m6: interpreter image=[%p,%p) base=%p entry=%p "
            "syscalls=%zu fs-prefixes=%zu\n",
            (void *)interpreter.image_start,
            (void *)interpreter.image_end,
            (void *)interpreter.load_bias,
            (void *)interpreter.entry_address,
            interpreter.patched_syscalls, interpreter_fs);

    if (interpreter.patched_syscalls == 0u) {
        errno = 0;
        fatal("M6 interpreter contains no trapped Linux syscall instructions");
    }

    void *stack_pointer = build_m3_initial_stack(
        guest_program, &program, &interpreter);
    enter_guest(stack_pointer, (void *)interpreter.entry_address);
}
