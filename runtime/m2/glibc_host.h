#ifndef HRT_M2_GLIBC_HOST_H
#define HRT_M2_GLIBC_HOST_H

#include "linux_x86_64.h"

#include <limits.h>
#include <stddef.h>
#include <stdint.h>

#define HRT_ELF_EI_NIDENT 16
#define HRT_ELF_EI_CLASS 4
#define HRT_ELF_EI_DATA 5
#define HRT_ELF_EI_VERSION 6
#define HRT_ELFCLASS64 2
#define HRT_ELFDATA2LSB 1
#define HRT_EV_CURRENT 1
#define HRT_ELFMAG "\177ELF"
#define HRT_SELFMAG 4
#define HRT_ET_DYN 3
#define HRT_EM_X86_64 62
#define HRT_PT_LOAD 1
#define HRT_PT_DYNAMIC 2
#define HRT_PT_INTERP 3
#define HRT_PT_PHDR 6
#define HRT_PF_X 1
#define HRT_PF_W 2
#define HRT_PF_R 4

#define HRT_M2_MAX_PHDRS 256
#define HRT_M2_STACK_SIZE (16u * 1024u * 1024u)
#define HRT_M2_SIGNAL_STACK_SIZE (256u * 1024u)
#define HRT_M2_MAX_STACK_WORDS 256
#define HRT_M2_BRK_RESERVE (256u * 1024u * 1024u)

typedef uint16_t HrtElf64Half;
typedef uint32_t HrtElf64Word;
typedef uint64_t HrtElf64Xword;
typedef uint64_t HrtElf64Addr;
typedef uint64_t HrtElf64Off;

typedef struct {
    unsigned char e_ident[HRT_ELF_EI_NIDENT];
    HrtElf64Half e_type;
    HrtElf64Half e_machine;
    HrtElf64Word e_version;
    HrtElf64Addr e_entry;
    HrtElf64Off e_phoff;
    HrtElf64Off e_shoff;
    HrtElf64Word e_flags;
    HrtElf64Half e_ehsize;
    HrtElf64Half e_phentsize;
    HrtElf64Half e_phnum;
    HrtElf64Half e_shentsize;
    HrtElf64Half e_shnum;
    HrtElf64Half e_shstrndx;
} HrtElf64Ehdr;

typedef struct {
    HrtElf64Word p_type;
    HrtElf64Word p_flags;
    HrtElf64Off p_offset;
    HrtElf64Addr p_vaddr;
    HrtElf64Addr p_paddr;
    HrtElf64Xword p_filesz;
    HrtElf64Xword p_memsz;
    HrtElf64Xword p_align;
} HrtElf64Phdr;

typedef struct {
    char host_path[PATH_MAX];
    char guest_path[PATH_MAX];
    char interpreter[PATH_MAX];
    HrtElf64Ehdr header;
    HrtElf64Phdr phdrs[HRT_M2_MAX_PHDRS];
    uintptr_t image_start;
    uintptr_t image_end;
    uintptr_t load_bias;
    uintptr_t entry_address;
    uintptr_t phdr_address;
    size_t patched_syscalls;
} HrtLoadedImage;

extern size_t g_host_page_size;
extern size_t g_guest_page_size;
extern char g_sysroot[PATH_MAX];
extern char g_guest_program[PATH_MAX];
extern int g_sysroot_fd;
extern uintptr_t g_original_fs_base;

void hrt_fatal(const char *message) __attribute__((noreturn));
uintptr_t hrt_align_down(uintptr_t value, size_t alignment);
uintptr_t hrt_align_up(uintptr_t value, size_t alignment);
size_t hrt_patch_linux_syscalls(unsigned char *start, size_t length);
int hrt_host_protection(uint32_t linux_protection);
int hrt_linux_errno(int host_errno);
long hrt_linux_result(long host_result);

HrtLoadedImage hrt_load_initial_elf(const char *host_path,
                                    const char *guest_path,
                                    int permit_interpreter);
void *hrt_build_initial_stack(const HrtLoadedImage *main_image,
                              const HrtLoadedImage *interpreter);
void hrt_initialize_process_state(void);
void hrt_install_syscall_bridge(void);
void hrt_enter_guest(void *stack_pointer, void *entry_point)
    __attribute__((noreturn));

#endif
