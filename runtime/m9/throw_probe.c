#define _GNU_SOURCE 1

#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>

/*
 * libstdc++ exports this helper as GLIBCXX_3.4.20.  The accompanying version
 * script gives the preload object the same symbol version, so only the exact
 * std::out_of_range path is intercepted; unrelated C++ exceptions continue to
 * use the packaged libstdc++ implementation.
 */
__attribute__((visibility("default"), noreturn))
void hrt_throw_out_of_range_fmt(const char *format, ...)
    __asm__("_ZSt24__throw_out_of_range_fmtPKcz");

void hrt_throw_out_of_range_fmt(const char *format, ...)
{
    void *caller = __builtin_return_address(0);
    Dl_info info = {0};
    (void)dladdr(caller, &info);

    const uintptr_t address = (uintptr_t)caller;
    const uintptr_t base = (uintptr_t)info.dli_fbase;
    const uintptr_t offset = address >= base ? address - base : 0u;
    char buffer[2048];
    int count = snprintf(
        buffer, sizeof(buffer),
        "HRT M9 THROW: format=%s caller=%p object=%s base=%p offset=0x%lx symbol=%s symbol-address=%p\n",
        format != NULL ? format : "(null)", caller,
        info.dli_fname != NULL ? info.dli_fname : "(unknown)",
        info.dli_fbase, (unsigned long)offset,
        info.dli_sname != NULL ? info.dli_sname : "(unknown)",
        info.dli_saddr);
    if (count > 0) {
        size_t length = (size_t)count;
        if (length > sizeof(buffer)) length = sizeof(buffer);
        (void)write(STDERR_FILENO, buffer, length);
    }

    /* Stop at the first exact out_of_range throw; no false continuation. */
    _exit(190);
}
