#include "hrt_m2.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void usage(const char *program) {
    fprintf(stderr,
            "usage: %s --root /host/rootfs --program /guest/program "
            "[--stop-at-entry]\n",
            program);
}

int main(int argc, char **argv) {
    int stop_at_entry = 0;
    if (argc == 6 && strcmp(argv[5], "--stop-at-entry") == 0) {
        stop_at_entry = 1;
    } else if (argc != 5) {
        usage(argv[0]);
        return 64;
    }
    if (strcmp(argv[1], "--root") != 0 ||
        strcmp(argv[3], "--program") != 0) {
        usage(argv[0]);
        return 64;
    }

    copy_checked(g_runtime.root, sizeof(g_runtime.root), argv[2],
                 "guest root path is too long");
    copy_checked(g_runtime.guest_program,
                 sizeof(g_runtime.guest_program), argv[4],
                 "guest program path is too long");
    if (g_runtime.guest_program[0] != '/') {
        errno = 0;
        fatal("guest program path must be absolute");
    }
    g_runtime.stop_at_entry = stop_at_entry;

    g_host_page_size = (size_t)getpagesize();
    install_sigill_handler();

    char program_path[HRT_MAX_PATH];
    resolve_guest_path(g_runtime.root, g_runtime.guest_program,
                       program_path, sizeof(program_path));
    LoadedElf program = load_elf(program_path);
    if (program.interp_path[0] == '\0') {
        errno = 0;
        fatal("M2 program does not contain PT_INTERP");
    }

    char interpreter_path[HRT_MAX_PATH];
    resolve_guest_path(g_runtime.root, program.interp_path,
                       interpreter_path, sizeof(interpreter_path));
    LoadedElf interpreter = load_elf(interpreter_path);
    if (interpreter.interp_path[0] != '\0') {
        errno = 0;
        fatal("nested PT_INTERP is unsupported");
    }

    fprintf(stderr,
            "hrt-m2: pages host=%zu guest=%zu program=[%p,%p) entry=%p "
            "syscalls=%zu fs=%zu interp=%s\n",
            g_host_page_size, g_guest_page_size,
            (void *)program.image_start, (void *)program.image_end,
            (void *)program.entry_address, program.patched_syscalls,
            program.patched_fs_prefixes, program.interp_path);
    fprintf(stderr,
            "hrt-m2: loader=[%p,%p) base=%p entry=%p syscalls=%zu fs=%zu\n",
            (void *)interpreter.image_start,
            (void *)interpreter.image_end,
            (void *)interpreter.load_bias,
            (void *)interpreter.entry_address,
            interpreter.patched_syscalls,
            interpreter.patched_fs_prefixes);

    if (g_runtime.stop_at_entry) {
        arm_entry_trap(program.entry_address);
        fprintf(stderr, "hrt-m3: armed original program entry trap at %p\n",
                (void *)program.entry_address);
    }

    void *stack_pointer = build_initial_stack(
        g_runtime.guest_program, &program, &interpreter);
    enter_guest(stack_pointer, (void *)interpreter.entry_address);
}
