#ifndef HRT_M3_H
#define HRT_M3_H

#include "../m1/hrt_m1.h"

#include <stddef.h>
#include <stdint.h>

LoadedElf load_unrelocated_elf(const char *path);
void set_prepatched_code_mode(int enabled);
int prepatched_code_mode_enabled(void);
size_t patch_guest_code(void *address, size_t length,
                        size_t *rewritten_fs_prefixes);
size_t patch_loaded_elf(LoadedElf *loaded,
                        size_t *rewritten_fs_prefixes);
void initialize_syscall_bridge(const char *root,
                               const char *guest_program);
void *build_m3_initial_stack(const char *guest_path,
                             const LoadedElf *program,
                             const LoadedElf *interpreter);

#endif
