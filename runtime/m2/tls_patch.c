#define _DARWIN_C_SOURCE 1
#include "hrt_m2.h"

#include <errno.h>
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
        case 0x29u: case 0x2bu:
        case 0x31u: case 0x33u:
        case 0x39u: case 0x3bu:
        case 0x80u: case 0x81u: case 0x83u:
        case 0x88u: case 0x89u: case 0x8au: case 0x8bu: case 0x8du:
        case 0xc6u: case 0xc7u:
        case 0xf7u: case 0xffu:
            return 1;
        case 0x0fu:
            if (index + 1u >= remaining) return 0;
            switch (bytes[index + 1u]) {
                case 0xafu:
                case 0xb1u:
                case 0xb6u: case 0xb7u:
                case 0xbeu: case 0xbfu:
                case 0xc1u:
                    return 1;
                default:
                    return 0;
            }
        default:
            return 0;
    }
}

size_t rewrite_linux_fs_to_gs(LoadedElf *loaded) {
    size_t rewritten = 0u;

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
            fatal("mprotect executable segment for TLS rewrite");
        }

        unsigned char *bytes = (unsigned char *)segment;
        size_t file_size = (size_t)phdr->p_filesz;
        for (size_t offset = 0u; offset < file_size; ++offset) {
            if (is_tls_memory_opcode(bytes + offset, file_size - offset)) {
                bytes[offset] = 0x65u; /* Linux FS -> macOS spare guest GS */
                ++rewritten;
            }
        }

        if (mprotect((void *)page_start, page_end - page_start,
                     host_protection(phdr->p_flags)) != 0) {
            fatal("restore executable segment protection after TLS rewrite");
        }
    }

    if (rewritten == 0u) {
        errno = 0;
    }
    return rewritten;
}
