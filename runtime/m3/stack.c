#define _DARWIN_C_SOURCE 1
#include "hrt_m3.h"

#include <errno.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

#define M3_AT_HWCAP 16
#define M3_AT_CLKTCK 17
#define M3_AT_HWCAP2 26
#define M3_AT_MINSIGSTKSZ 51

static uintptr_t push_bytes(uintptr_t *cursor, uintptr_t floor,
                            const void *source, size_t size) {
    if (*cursor < floor || size > *cursor - floor) {
        errno = 0;
        fatal("M3 initial stack string block overflow");
    }
    *cursor -= size;
    memcpy((void *)*cursor, source, size);
    return *cursor;
}

void *build_m3_initial_stack(const char *guest_path,
                             const LoadedElf *program,
                             const LoadedElf *interpreter) {
    unsigned char *base = mmap(NULL, HRT_STACK_SIZE,
                               PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED) fatal("mmap M3 guest stack");
    uintptr_t floor = (uintptr_t)base + g_page_size;
    uintptr_t cursor = (uintptr_t)base + HRT_STACK_SIZE;

    uintptr_t argv0 = push_bytes(&cursor, floor, guest_path,
                                 strlen(guest_path) + 1u);

    static const char milestone[] = "HRT_MILESTONE=M3";
    static const char language[] = "LANG=C";
    static const char home[] = "HOME=/tmp/hrt-home";
    static const char tmpdir[] = "TMPDIR=/tmp";
    static const char library_path[] =
        "LD_LIBRARY_PATH=/opt/hnc/hoffice11/Bin:"
        "/opt/hnc/hoffice11/Bin/qt/lib:"
        "/lib/x86_64-linux-gnu:"
        "/usr/lib/x86_64-linux-gnu:/lib64";
    uintptr_t env0 = push_bytes(&cursor, floor, milestone,
                                sizeof(milestone));
    uintptr_t env1 = push_bytes(&cursor, floor, language,
                                sizeof(language));
    uintptr_t env2 = push_bytes(&cursor, floor, home,
                                sizeof(home));
    uintptr_t env3 = push_bytes(&cursor, floor, tmpdir,
                                sizeof(tmpdir));
    uintptr_t env4 = push_bytes(&cursor, floor, library_path,
                                sizeof(library_path));

    static const char platform[] = "x86_64";
    uintptr_t platform_pointer = push_bytes(
        &cursor, floor, platform, sizeof(platform));

    cursor = align_down(cursor - 16u, 16u);
    if (cursor < floor) {
        errno = 0;
        fatal("M3 initial stack random block overflow");
    }
    unsigned char *random_bytes = (unsigned char *)cursor;
    for (size_t index = 0; index < 16u; ++index) {
        random_bytes[index] = (unsigned char)(0x71u + index);
    }

    uint64_t words[HRT_MAX_STACK_WORDS];
    size_t count = 0u;
#define WORD(value) do { \
    if (count >= HRT_MAX_STACK_WORDS) fatal("M3 initial stack overflow"); \
    words[count++] = (uint64_t)(value); \
} while (0)
#define AUX(type, value) do { WORD(type); WORD(value); } while (0)

    WORD(1);
    WORD(argv0);
    WORD(0);
    WORD(env0);
    WORD(env1);
    WORD(env2);
    WORD(env3);
    WORD(env4);
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
    AUX(M3_AT_HWCAP, 0);
    AUX(M3_AT_CLKTCK, 100);
    AUX(AT_SECURE, 0);
    AUX(AT_RANDOM, cursor);
    AUX(M3_AT_HWCAP2, 0);
    AUX(AT_EXECFN, argv0);
    AUX(M3_AT_MINSIGSTKSZ, 2048);
    AUX(AT_NULL, 0);
#undef AUX
#undef WORD

    size_t words_size = count * sizeof(uint64_t);
    if (cursor < floor || words_size > cursor - floor) {
        errno = 0;
        fatal("M3 initial stack vector overflow");
    }
    uintptr_t stack_pointer = align_down(cursor - words_size, 16u);
    if (stack_pointer < floor) {
        errno = 0;
        fatal("M3 initial stack does not fit");
    }
    memcpy((void *)stack_pointer, words, words_size);
    return (void *)stack_pointer;
}
