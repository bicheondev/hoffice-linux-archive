#define _DARWIN_C_SOURCE 1
#include "hrt_m0.h"

#include <errno.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

void *build_initial_stack(const char *guest_path, const LoadedElf *loaded) {
    unsigned char *base = mmap(NULL, HRT_STACK_SIZE, PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED) fatal("mmap guest stack");
    uintptr_t cursor = (uintptr_t)base + HRT_STACK_SIZE;

    size_t path_length = strlen(guest_path) + 1u;
    cursor -= path_length;
    memcpy((void *)cursor, guest_path, path_length);
    uintptr_t argv0 = cursor;

    static const char environment[] = "HRT_M0=1";
    cursor -= sizeof(environment);
    memcpy((void *)cursor, environment, sizeof(environment));
    uintptr_t env0 = cursor;

    cursor = align_down(cursor - 16u, 16u);
    unsigned char *random_bytes = (unsigned char *)cursor;
    for (size_t index = 0; index < 16u; ++index) random_bytes[index] = (unsigned char)(0x41u + index);

    uint64_t words[HRT_MAX_STACK_WORDS];
    size_t count = 0;
#define WORD(value) do { if (count >= HRT_MAX_STACK_WORDS) fatal("initial stack overflow"); words[count++] = (uint64_t)(value); } while (0)
#define AUX(type, value) do { WORD(type); WORD(value); } while (0)
    WORD(1); WORD(argv0); WORD(0); WORD(env0); WORD(0);
    AUX(AT_PHDR, loaded->phdr_address);
    AUX(AT_PHENT, sizeof(Elf64_Phdr));
    AUX(AT_PHNUM, loaded->header.e_phnum);
    AUX(AT_PAGESZ, g_page_size);
    AUX(AT_ENTRY, loaded->header.e_entry);
    AUX(AT_UID, getuid()); AUX(AT_EUID, geteuid());
    AUX(AT_GID, getgid()); AUX(AT_EGID, getegid());
    AUX(AT_SECURE, 0); AUX(AT_RANDOM, cursor); AUX(AT_EXECFN, argv0); AUX(AT_NULL, 0);
#undef AUX
#undef WORD

    uintptr_t stack_pointer = align_down(cursor - count * sizeof(uint64_t), 16u);
    if (stack_pointer < (uintptr_t)base + g_page_size) {
        errno = 0;
        fatal("initial stack does not fit");
    }
    memcpy((void *)stack_pointer, words, count * sizeof(uint64_t));
    return (void *)stack_pointer;
}
