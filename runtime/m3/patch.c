#define _DARWIN_C_SOURCE 1
#include "hrt_m3.h"

#include <stdint.h>
#include <sys/mman.h>

static int host_protection(uint32_t flags) {
    int protection = 0;
    if ((flags & PF_R) != 0u) protection |= PROT_READ;
    if ((flags & PF_W) != 0u) protection |= PROT_WRITE;
    if ((flags & PF_X) != 0u) protection |= PROT_EXEC;
    return protection;
}

static int is_legacy_prefix(unsigned char value) {
    return value == 0x66u || value == 0x67u ||
           value == 0xf2u || value == 0xf3u;
}

static int is_tls_memory_opcode(const unsigned char *bytes,
                                size_t remaining) {
    if (remaining < 2u || bytes[0] != 0x64u) return 0;

    size_t index = 1u;
    while (index < remaining && is_legacy_prefix(bytes[index])) ++index;
    if (index < remaining && bytes[index] >= 0x40u && bytes[index] <= 0x4fu) {
        ++index;
    }
    if (index >= remaining) return 0;

    switch (bytes[index]) {
        case 0x01u: case 0x03u:
        case 0x09u: case 0x0bu:
        case 0x21u: case 0x23u:
        case 0x29u: case 0x2bu:
        case 0x31u: case 0x33u:
        case 0x39u: case 0x3bu:
        case 0x63u:
        case 0x80u: case 0x81u: case 0x83u:
        case 0x86u: case 0x87u:
        case 0x88u: case 0x89u: case 0x8au: case 0x8bu: case 0x8du:
        case 0xc6u: case 0xc7u:
        case 0xf6u: case 0xf7u: case 0xfeu: case 0xffu:
            return 1;
        case 0x0fu:
            if (index + 1u >= remaining) return 0;
            switch (bytes[index + 1u]) {
                case 0xafu:
                case 0xb0u: case 0xb1u:
                case 0xb6u: case 0xb7u:
                case 0xbeu: case 0xbfu:
                case 0xc0u: case 0xc1u:
                    return 1;
                default:
                    return 0;
            }
        default:
            return 0;
    }
}

size_t patch_guest_code(void *address, size_t length,
                        size_t *rewritten_fs_prefixes) {
    unsigned char *bytes = address;
    size_t patched_syscalls = 0u;
    size_t patched_fs = 0u;

    for (size_t offset = 0u; offset < length; ++offset) {
        if (offset + 1u < length &&
            bytes[offset] == 0x0fu && bytes[offset + 1u] == 0x05u) {
            bytes[offset + 1u] = 0x0bu; /* syscall -> ud2 */
            ++patched_syscalls;
            ++offset;
            continue;
        }
        if (is_tls_memory_opcode(bytes + offset, length - offset)) {
            bytes[offset] = 0x65u; /* Linux FS -> spare guest GS */
            ++patched_fs;
        }
    }

    if (rewritten_fs_prefixes != NULL) {
        *rewritten_fs_prefixes += patched_fs;
    }
    return patched_syscalls;
}

size_t patch_loaded_elf(LoadedElf *loaded,
                        size_t *rewritten_fs_prefixes) {
    size_t patched_syscalls = 0u;

    for (uint16_t index = 0; index < loaded->header.e_phnum; ++index) {
        const Elf64_Phdr *phdr = &loaded->phdrs[index];
        if (phdr->p_type != PT_LOAD || phdr->p_memsz == 0u ||
            (phdr->p_flags & PF_X) == 0u) {
            continue;
        }

        uintptr_t segment = loaded->load_bias + (uintptr_t)phdr->p_vaddr;
        uintptr_t page_start = align_down(segment, g_page_size);
        uintptr_t page_end = align_up(
            loaded->load_bias + (uintptr_t)(phdr->p_vaddr + phdr->p_memsz),
            g_page_size);
        if (mprotect((void *)page_start, page_end - page_start,
                     PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
            fatal("mprotect executable segment for M3 patching");
        }
        patched_syscalls += patch_guest_code(
            (void *)segment, (size_t)phdr->p_filesz,
            rewritten_fs_prefixes);
        if (mprotect((void *)page_start, page_end - page_start,
                     host_protection(phdr->p_flags)) != 0) {
            fatal("restore executable segment after M3 patching");
        }
    }

    loaded->patched_syscalls += patched_syscalls;
    return patched_syscalls;
}
