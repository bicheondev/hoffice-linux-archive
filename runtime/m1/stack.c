#define _DARWIN_C_SOURCE 1
#include "hrt_m1.h"

#include <errno.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

static uintptr_t push_bytes(uintptr_t *cursor, uintptr_t floor,
                            const void *source, size_t size) {
    if (*cursor < floor || size > *cursor - floor) {
        errno = 0;
        fatal("initial stack string block overflow");
    }
    *cursor -= size;
    memcpy((void *)*cursor, source, size);
    return *cursor;
}

void *build_initial_stack(const char *guest_path,
                          const LoadedElf *program,
                          const LoadedElf *interpreter) {
    unsigned char *base = mmap(NULL, HRT_STACK_SIZE, PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED) fatal("mmap guest stack");
    uintptr_t floor = (uintptr_t)base + g_page_size;
    uintptr_t cursor = (uintptr_t)base + HRT_STACK_SIZE;

    size_t path_length = strlen(guest_path) + 1u;
    uintptr_t argv0 = push_bytes(&cursor, floor, guest_path, path_length);

    static const char environment[] = "HRT_MILESTONE=M1";
    uintptr_t env0 = push_bytes(&cursor, floor, environment,
                                sizeof(environment));

    static const char platform[] = "x86_64";
    uintptr_t platform_pointer = push_bytes(&cursor, floor, platform,
                                            sizeof(platform));

    cursor = align_down(cursor - 16u, 16u);
    if (cursor < floor) {
        errno = 0;
        fatal("initial stack random block overflow");
    }
    unsigned char *random_bytes = (unsigned char *)cursor;
    for (size_t index = 0; index < 16u; ++index) {
        random_bytes[index] = (unsigned char)(0x51u + index);
    }

    uint64_t words[HRT_MAX_STACK_WORDS];
    size_t count = 0;
#define WORD(value) do { \
    if (count >= HRT_MAX_STACK_WORDS) fatal("initial stack word overflow"); \
    words[count++] = (uint64_t)(value); \
} while (0)
#define AUX(type, value) do { WORD(type); WORD(value); } while (0)

    WORD(1);
    WORD(argv0);
    WORD(0);
    WORD(env0);
    WORD(0);
    AUX(AT_PHDR, program->phdr_address);
    AUX(AT_PHENT, sizeof(Elf64_Phdr));
    AUX(AT_PHNUM, program->header.e_phnum);
    AUX(AT_PAGESZ, g_page_size);
    AUX(AT_BASE, interpreter->load_bias);
    AUX(AT_FLAGS, 0);
    AUX(AT_ENTRY, program->entry_address);
    AUX(AT_UID, getuid());
    AUX(AT_EUID, geteuid());
    AUX(AT_GID, getgid());
    AUX(AT_EGID, getegid());
    AUX(AT_PLATFORM, platform_pointer);
    AUX(AT_SECURE, 0);
    AUX(AT_RANDOM, cursor);
    AUX(AT_EXECFN, argv0);
    AUX(AT_NULL, 0);
#undef AUX
#undef WORD

    size_t words_size = count * sizeof(uint64_t);
    if (cursor < floor || words_size > cursor - floor) {
        errno = 0;
        fatal("initial stack vector block overflow");
    }
    uintptr_t stack_pointer = align_down(cursor - words_size, 16u);
    if (stack_pointer < floor) {
        errno = 0;
        fatal("initial stack does not fit");
    }
    memcpy((void *)stack_pointer, words, words_size);
    return (void *)stack_pointer;
}
