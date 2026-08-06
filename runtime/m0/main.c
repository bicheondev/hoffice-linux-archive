#include "hrt_m0.h"

#include <errno.h>
#include <stdio.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s /path/to/static-linux-x86_64-elf\n", argv[0]);
        return 64;
    }
    g_page_size = (size_t)getpagesize();
    install_sigill_handler();
    LoadedElf loaded = load_static_elf(argv[1]);
    if (loaded.patched_syscalls == 0) {
        errno = 0;
        fatal("no Linux syscall instructions were found");
    }
    fprintf(stderr, "hrt-m0: mapped ELF [%p, %p), entry=%p, patched=%zu\n",
            (void *)loaded.image_start, (void *)loaded.image_end,
            (void *)(uintptr_t)loaded.header.e_entry, loaded.patched_syscalls);
    void *stack_pointer = build_initial_stack(argv[1], &loaded);
    enter_guest(stack_pointer, (void *)(uintptr_t)loaded.header.e_entry);
}
