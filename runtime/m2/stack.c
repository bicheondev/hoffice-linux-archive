#define _DARWIN_C_SOURCE 1
#include "hrt_m2.h"

#include <errno.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

static uintptr_t push_string(uintptr_t *cursor, const char *value) {
    size_t length = strlen(value) + 1u;
    *cursor -= length;
    memcpy((void *)*cursor, value, length);
    return *cursor;
}

void *build_initial_stack(const char *guest_path,
                          const LoadedElf *main_image,
                          const LoadedElf *interpreter_image) {
    unsigned char *base = mmap(NULL, HRT_STACK_SIZE, PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED) fatal("mmap guest stack");
    uintptr_t cursor = (uintptr_t)base + HRT_STACK_SIZE;

    uintptr_t argv0 = push_string(&cursor, guest_path);
    uintptr_t env_ld = push_string(
        &cursor,
        "LD_LIBRARY_PATH=/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu:/lib64");
    uintptr_t env_lang = push_string(&cursor, "LANG=C");
    uintptr_t env_runtime = push_string(&cursor, "HRT_M2=1");
    uintptr_t platform = push_string(&cursor, "x86_64");

    cursor = align_down(cursor - 16u, 16u);
    uintptr_t random_address = cursor;
    unsigned char *random_bytes = (unsigned char *)random_address;
    for (size_t index = 0; index < 16u; ++index) {
        random_bytes[index] = (unsigned char)(0x61u + index);
    }

    uint64_t words[HRT_MAX_STACK_WORDS];
    size_t count = 0;
#define WORD(value) do { \
    if (count >= HRT_MAX_STACK_WORDS) fatal("initial stack overflow"); \
    words[count++] = (uint64_t)(value); \
} while (0)
#define AUX(type, value) do { WORD(type); WORD(value); } while (0)

    WORD(1);
    WORD(argv0);
    WORD(0);
    WORD(env_ld);
    WORD(env_lang);
    WORD(env_runtime);
    WORD(0);

    AUX(AT_PHDR, main_image->phdr_address);
    AUX(AT_PHENT, sizeof(Elf64_Phdr));
    AUX(AT_PHNUM, main_image->header.e_phnum);
    AUX(AT_PAGESZ, g_page_size);
    AUX(AT_BASE, interpreter_image->load_bias);
    AUX(AT_ENTRY, main_image->entry);
    AUX(AT_UID, getuid());
    AUX(AT_EUID, geteuid());
    AUX(AT_GID, getgid());
    AUX(AT_EGID, getegid());
    AUX(AT_PLATFORM, platform);
    AUX(AT_HWCAP, 0);
    AUX(AT_CLKTCK, 100);
    AUX(AT_SECURE, 0);
    AUX(AT_RANDOM, random_address);
    AUX(AT_HWCAP2, 0);
    AUX(AT_EXECFN, argv0);
    AUX(AT_MINSIGSTKSZ, 2048);
    AUX(AT_NULL, 0);

#undef AUX
#undef WORD

    uintptr_t stack_pointer = align_down(
        cursor - count * sizeof(uint64_t), 16u);
    if (stack_pointer < (uintptr_t)base + g_page_size) {
        errno = 0;
        fatal("initial stack does not fit");
    }
    memcpy((void *)stack_pointer, words, count * sizeof(uint64_t));
    return (void *)stack_pointer;
}
