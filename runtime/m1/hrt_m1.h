#ifndef HRT_M1_H
#define HRT_M1_H

#include "elf64_abi.h"
#include <stddef.h>
#include <stdint.h>

#define HRT_STACK_SIZE (8u * 1024u * 1024u)
#define HRT_ALTSTACK_SIZE (128u * 1024u)
#define HRT_MAX_PHDRS 128
#define HRT_MAX_STACK_WORDS 160
#define HRT_MAX_INTERP 512
#define HRT_MAX_PATH 4096

typedef struct {
    Elf64_Ehdr header;
    Elf64_Phdr phdrs[HRT_MAX_PHDRS];
    uintptr_t image_start;
    uintptr_t image_end;
    uintptr_t load_bias;
    uintptr_t entry_address;
    uintptr_t phdr_address;
    uintptr_t dynamic_address;
    size_t dynamic_size;
    size_t patched_syscalls;
    size_t applied_relocations;
    char interp_path[HRT_MAX_INTERP];
} LoadedElf;

extern size_t g_page_size;

void fatal(const char *message) __attribute__((noreturn));
uintptr_t align_down(uintptr_t value, size_t alignment);
uintptr_t align_up(uintptr_t value, size_t alignment);
void resolve_guest_path(const char *root, const char *guest_path,
                        char *output, size_t output_size);
void install_sigill_handler(void);
LoadedElf load_elf(const char *path);
void *build_initial_stack(const char *guest_path,
                          const LoadedElf *program,
                          const LoadedElf *interpreter);
void enter_guest(void *stack_pointer, void *entry_point) __attribute__((noreturn));

#endif
