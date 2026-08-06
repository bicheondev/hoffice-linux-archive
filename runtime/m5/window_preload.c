#include <stddef.h>
#include <stdint.h>

#define HRT_HOST_CREATE_WINDOW UINT64_C(0x7ff00001)

static long raw_syscall4(long number, long argument1, long argument2,
                         long argument3, long argument4) {
    register long r10 __asm__("r10") = argument4;
    long result;
    __asm__ volatile(
        "syscall"
        : "=a"(result)
        : "0"(number), "D"(argument1), "S"(argument2),
          "d"(argument3), "r"(r10)
        : "rcx", "r11", "memory");
    return result;
}

static void raw_write(int fd, const char *text, size_t length) {
    (void)raw_syscall4(1, fd, (long)(uintptr_t)text,
                       (long)length, 0);
}

__attribute__((constructor))
static void request_appkit_window(void) {
    static const char title[] =
        "한컴오피스 2022 Beta — HRT M5";
    static const char marker[] =
        "HRT M5: guest preload requested AppKit window\n";
    long result = raw_syscall4(
        (long)HRT_HOST_CREATE_WINDOW,
        (long)(uintptr_t)title,
        (long)(sizeof(title) - 1u),
        920,
        640);
    raw_write(2, marker, sizeof(marker) - 1u);
    if (result < 0) {
        static const char failure[] =
            "HRT M5: AppKit request failed\n";
        raw_write(2, failure, sizeof(failure) - 1u);
    }
}
