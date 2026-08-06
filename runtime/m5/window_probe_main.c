#include <stddef.h>
#include <stdint.h>

#define HRT_HOST_VISIBLE_WINDOWS UINT64_C(0x7ff00002)

typedef struct {
    int64_t tv_sec;
    int64_t tv_nsec;
} LinuxTimespec;

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

static void sleep_milliseconds(long milliseconds) {
    LinuxTimespec request = {
        .tv_sec = milliseconds / 1000,
        .tv_nsec = (milliseconds % 1000) * 1000000,
    };
    (void)raw_syscall4(35, (long)(uintptr_t)&request, 0, 0, 0);
}

int main(void) {
    long visible = 0;
    for (int attempt = 0; attempt < 500; ++attempt) {
        visible = raw_syscall4(
            (long)HRT_HOST_VISIBLE_WINDOWS, 0, 0, 0, 0);
        if (visible > 0) break;
        sleep_milliseconds(10);
    }
    if (visible <= 0) {
        static const char failure[] =
            "HRT M5: AppKit window was not observed\n";
        raw_write(2, failure, sizeof(failure) - 1u);
        return 2;
    }

    static const char success[] =
        "HRT M5: guest observed visible AppKit window\n";
    raw_write(1, success, sizeof(success) - 1u);
    sleep_milliseconds(1200);
    return 0;
}
