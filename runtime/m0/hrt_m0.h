#ifndef HRT_M0_H
#define HRT_M0_H

#include "elf64_abi.h"
#include <stddef.h>
#include <stdint.h>

#define HRT_STACK_SIZE (8u * 1024u * 1024u)
#define HRT_ALTSTACK_SIZE (128u * 1024u)
#define HRT_MAX_PHDRS 128
#define HRT_MAX_STACK_WORDS 128

typedef struct {
    Elf64_Ehdr header;
    Elf64_Phdr phdrs[HRT_MAX_PHDRS];
    uintptr_t image_start;
    uintptr_t image_end;
    uintptr_t load_bias;
    uintptr_t entry_address;
    uintptr_t phdr_address;
    size_t patched_syscalls;
} LoadedElf;

extern size_t g_page_size;

void fatal(const char *message) __attribute__((noreturn));
uintptr_t align_down(uintptr_t value, size_t alignment);
uintptr_t align_up(uintptr_t value, size_t alignment);
void install_sigill_handler(void);
LoadedElf load_elf(const char *path);
void *build_initial_stack(const char *guest_path, const LoadedElf *loaded);
void enter_guest(void *stack_pointer, void *entry_point) __attribute__((noreturn));

#endif
