#ifndef HRT_M2_H
#define HRT_M2_H

#include "../m1/elf64_abi.h"

#include <stddef.h>
#include <stdint.h>

#define HRT_STACK_SIZE (16u * 1024u * 1024u)
#define HRT_ALTSTACK_SIZE (256u * 1024u)
#define HRT_MAX_PHDRS 256
#define HRT_MAX_STACK_WORDS 256
#define HRT_MAX_INTERP 512
#define HRT_MAX_PATH 4096
#define HRT_BRK_RESERVE (64u * 1024u * 1024u)
#define HRT_MAX_TRACKED_FDS 256
#define HRT_MAX_MAPPINGS 512

#ifndef AT_HWCAP
#define AT_HWCAP 16
#endif
#ifndef AT_CLKTCK
#define AT_CLKTCK 17
#endif
#ifndef AT_HWCAP2
#define AT_HWCAP2 26
#endif
#ifndef AT_MINSIGSTKSZ
#define AT_MINSIGSTKSZ 51
#endif

typedef struct {
    Elf64_Ehdr header;
    Elf64_Phdr phdrs[HRT_MAX_PHDRS];
    uintptr_t image_start;
    uintptr_t image_end;
    uintptr_t load_bias;
    uintptr_t entry_address;
    uintptr_t phdr_address;
    size_t patched_syscalls;
    size_t patched_fs_prefixes;
    char interp_path[HRT_MAX_INTERP];
} LoadedElf;

typedef struct {
    int valid;
    int fd;
    uintptr_t start;
    size_t length;
    uint64_t file_offset;
} GuestMapping;

typedef struct {
    char root[HRT_MAX_PATH];
    char guest_program[HRT_MAX_PATH];
    char fd_paths[HRT_MAX_TRACKED_FDS][HRT_MAX_PATH];
    GuestMapping mappings[HRT_MAX_MAPPINGS];
    uintptr_t brk_base;
    uintptr_t brk_current;
    uintptr_t brk_limit;
    uintptr_t clear_child_tid;
    uintptr_t host_gs_base;
    uintptr_t guest_gs_base;
    uintptr_t entry_trap_address;
    unsigned char entry_trap_original[2];
    int guest_gs_active;
    int stop_at_entry;
    int entry_trap_armed;
    uint64_t syscall_count;
    uint64_t unsupported_count;
    uint64_t code_syscall_patches;
    uint64_t code_fs_patches;
} RuntimeState;

#ifdef __cplusplus
extern "C" {
#endif

extern size_t g_host_page_size;
extern size_t g_guest_page_size;
extern RuntimeState g_runtime;

void fatal(const char *message) __attribute__((noreturn));
uintptr_t align_down(uintptr_t value, size_t alignment);
uintptr_t align_up(uintptr_t value, size_t alignment);
void copy_checked(char *output, size_t output_size, const char *input,
                  const char *label);
void resolve_guest_path(const char *root, const char *guest_path,
                        char *output, size_t output_size);
void translate_guest_path(const char *guest_path,
                          char *host_path, size_t host_path_size);

size_t patch_guest_code(void *start, size_t length,
                        const char *host_path, uint64_t file_offset,
                        size_t *fs_prefix_count);
void arm_entry_trap(uintptr_t address);
void record_fd_path(int fd, const char *host_path);
const char *lookup_fd_path(int fd);
void clear_fd_path(int fd);
void copy_fd_path(int source_fd, int target_fd);
void record_guest_mapping(uintptr_t start, size_t length, int fd,
                          uint64_t file_offset);
void patch_guest_mappings(uintptr_t start, size_t length);

LoadedElf load_elf(const char *path);
void *build_initial_stack(const char *guest_path,
                          const LoadedElf *program,
                          const LoadedElf *interpreter);
void install_sigill_handler(void);
void enter_guest(void *stack_pointer, void *entry_point)
    __attribute__((noreturn));

#ifdef __cplusplus
}
#endif

#endif
