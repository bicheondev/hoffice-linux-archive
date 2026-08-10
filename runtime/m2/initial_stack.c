#define _DARWIN_C_SOURCE 1
#include "glibc_host.h"

#include <errno.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

static uintptr_t copy_bytes(uintptr_t cursor, uintptr_t stack_base,
                            const void *source, size_t size) {
    if (cursor < stack_base || size > cursor - stack_base) {
        errno = 0;
        hrt_fatal("guest stack string area overflow");
    }
    cursor -= size;
    memcpy((void *)cursor, source, size);
    return cursor;
}

void *hrt_build_initial_stack(const HrtLoadedImage *main_image,
                              const HrtLoadedImage *interpreter) {
    unsigned char *stack = mmap(NULL, HRT_M2_STACK_SIZE,
                                PROT_READ | PROT_WRITE,
                                MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (stack == MAP_FAILED) hrt_fatal("mmap guest initial stack");
    uintptr_t stack_base = (uintptr_t)stack;
    uintptr_t cursor = stack_base + HRT_M2_STACK_SIZE;

    size_t path_size = strlen(g_guest_program) + 1u;
    cursor = copy_bytes(cursor, stack_base, g_guest_program, path_size);
    uintptr_t argv0 = cursor;

    static const char ld_library_path[] =
        "LD_LIBRARY_PATH=/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu:" 
        "/lib64:/usr/lib64";
    cursor = copy_bytes(cursor, stack_base,
                        ld_library_path, sizeof(ld_library_path));
    uintptr_t env_ld_library_path = cursor;

    static const char language[] = "LANG=C";
    cursor = copy_bytes(cursor, stack_base, language, sizeof(language));
    uintptr_t env_language = cursor;

    static const char runtime_marker[] = "HRT_M2=1";
    cursor = copy_bytes(cursor, stack_base,
                        runtime_marker, sizeof(runtime_marker));
    uintptr_t env_runtime = cursor;

    static const char platform[] = "x86_64";
    cursor = copy_bytes(cursor, stack_base, platform, sizeof(platform));
    uintptr_t platform_pointer = cursor;

    cursor = hrt_align_down(cursor, 16u);
    if (cursor < stack_base + 16u) {
        errno = 0;
        hrt_fatal("guest stack random area overflow");
    }
    cursor -= 16u;
    uintptr_t random_pointer = cursor;
    unsigned char *random_bytes = (unsigned char *)random_pointer;
    for (size_t index = 0; index < 16u; ++index) {
        random_bytes[index] = (unsigned char)(0x61u + index);
    }

    uint64_t words[HRT_M2_MAX_STACK_WORDS];
    size_t count = 0;
#define PUSH_WORD(value) do { \
    if (count >= HRT_M2_MAX_STACK_WORDS) { \
        errno = 0; \
        hrt_fatal("guest initial stack vector overflow"); \
    } \
    words[count++] = (uint64_t)(value); \
} while (0)
#define PUSH_AUX(type, value) do { PUSH_WORD(type); PUSH_WORD(value); } while (0)

    PUSH_WORD(1); /* argc */
    PUSH_WORD(argv0);
    PUSH_WORD(0); /* argv terminator */
    PUSH_WORD(env_runtime);
    PUSH_WORD(env_language);
    PUSH_WORD(env_ld_library_path);
    PUSH_WORD(0); /* envp terminator */

    PUSH_AUX(LINUX_AT_PHDR, main_image->phdr_address);
    PUSH_AUX(LINUX_AT_PHENT, sizeof(HrtElf64Phdr));
    PUSH_AUX(LINUX_AT_PHNUM, main_image->header.e_phnum);
    PUSH_AUX(LINUX_AT_PAGESZ, g_guest_page_size);
    PUSH_AUX(LINUX_AT_BASE, interpreter->load_bias);
    PUSH_AUX(LINUX_AT_FLAGS, 0);
    PUSH_AUX(LINUX_AT_ENTRY, main_image->entry_address);
    PUSH_AUX(LINUX_AT_UID, getuid());
    PUSH_AUX(LINUX_AT_EUID, geteuid());
    PUSH_AUX(LINUX_AT_GID, getgid());
    PUSH_AUX(LINUX_AT_EGID, getegid());
    PUSH_AUX(LINUX_AT_PLATFORM, platform_pointer);
    PUSH_AUX(LINUX_AT_HWCAP, 0);
    PUSH_AUX(LINUX_AT_CLKTCK, 100);
    PUSH_AUX(LINUX_AT_SECURE, 0);
    PUSH_AUX(LINUX_AT_RANDOM, random_pointer);
    PUSH_AUX(LINUX_AT_HWCAP2, 0);
    PUSH_AUX(LINUX_AT_RSEQ_FEATURE_SIZE, 0);
    PUSH_AUX(LINUX_AT_RSEQ_ALIGN, 0);
    PUSH_AUX(LINUX_AT_EXECFN, argv0);
    PUSH_AUX(LINUX_AT_SYSINFO_EHDR, 0);
    PUSH_AUX(LINUX_AT_MINSIGSTKSZ, 2048);
    PUSH_AUX(LINUX_AT_NULL, 0);

#undef PUSH_AUX
#undef PUSH_WORD

    size_t vector_size = count * sizeof(uint64_t);
    if (cursor < stack_base || vector_size > cursor - stack_base) {
        errno = 0;
        hrt_fatal("guest initial stack vector does not fit");
    }
    uintptr_t stack_pointer = hrt_align_down(cursor - vector_size, 16u);
    if (stack_pointer < stack_base + g_host_page_size) {
        errno = 0;
        hrt_fatal("guest stack vector is too close to the mapping base");
    }
    memcpy((void *)stack_pointer, words, vector_size);
    return (void *)stack_pointer;
}
