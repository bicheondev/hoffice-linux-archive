#include "appkit_adapter.h"

#include <stddef.h>
#include <stdint.h>

#define LINUX_SYS_WRITE UINT64_C(1)
#define LINUX_SYS_EXIT_GROUP UINT64_C(231)

static int64_t linux_syscall3(uint64_t number,
                              uint64_t argument1,
                              uint64_t argument2,
                              uint64_t argument3) {
    uint64_t result;
    register uint64_t register10 __asm__("r10") = 0u;
    register uint64_t register8 __asm__("r8") = 0u;
    register uint64_t register9 __asm__("r9") = 0u;
    __asm__ volatile(
        "syscall"
        : "=a"(result), "+r"(register10),
          "+r"(register8), "+r"(register9)
        : "0"(number), "D"(argument1), "S"(argument2), "d"(argument3)
        : "rcx", "r11", "cc", "memory");
    return (int64_t)result;
}

static int64_t host_call(uint64_t opcode,
                         uint64_t argument1,
                         uint64_t argument2,
                         uint64_t argument3,
                         uint64_t argument4,
                         uint64_t argument5) {
    uint64_t result;
    register uint64_t register10 __asm__("r10") = argument3;
    register uint64_t register8 __asm__("r8") = argument4;
    register uint64_t register9 __asm__("r9") = argument5;
    __asm__ volatile(
        "syscall"
        : "=a"(result), "+r"(register10),
          "+r"(register8), "+r"(register9)
        : "0"(HRT_M6_HOSTCALL_SYSCALL),
          "D"(opcode), "S"(argument1), "d"(argument2)
        : "rcx", "r11", "cc", "memory");
    return (int64_t)result;
}

static void write_bytes(const char *text, size_t length) {
    (void)linux_syscall3(LINUX_SYS_WRITE, UINT64_C(1),
                         (uint64_t)(uintptr_t)text, (uint64_t)length);
}

static size_t append_literal(char *buffer, size_t cursor,
                             const char *text, size_t length) {
    for (size_t index = 0u; index < length; ++index) {
        buffer[cursor++] = text[index];
    }
    return cursor;
}

static size_t append_hex(char *buffer, size_t cursor, uint64_t value) {
    static const char digits[] = "0123456789abcdef";
    buffer[cursor++] = '0';
    buffer[cursor++] = 'x';
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned int digit = (unsigned int)((value >> (unsigned int)shift) & 0xfu);
        if (digit != 0u || started || shift == 0) {
            started = 1;
            buffer[cursor++] = digits[digit];
        }
    }
    return cursor;
}

static void write_status(int64_t handle, int64_t flags, int64_t capture) {
    char buffer[192];
    size_t cursor = 0u;
    static const char prefix[] = "HRT M6 GUEST: handle=";
    static const char middle1[] = " flags=";
    static const char middle2[] = " capture=";
    cursor = append_literal(buffer, cursor, prefix, sizeof(prefix) - 1u);
    cursor = append_hex(buffer, cursor, (uint64_t)handle);
    cursor = append_literal(buffer, cursor, middle1, sizeof(middle1) - 1u);
    cursor = append_hex(buffer, cursor, (uint64_t)flags);
    cursor = append_literal(buffer, cursor, middle2, sizeof(middle2) - 1u);
    cursor = append_hex(buffer, cursor, (uint64_t)capture);
    buffer[cursor++] = '\n';
    write_bytes(buffer, cursor);
}

__attribute__((noreturn))
static void terminate(int status) {
    (void)linux_syscall3(LINUX_SYS_EXIT_GROUP,
                         (uint64_t)(unsigned int)status, 0u, 0u);
    for (;;) {
        __asm__ volatile("pause");
    }
}

__attribute__((noreturn, visibility("default")))
void _start(void) {
    static const char title[] = "HRT M6 Linux Guest Window";
    static const char pass[] =
        "HRT M6 GUEST PASS: trapped Linux host call created a visible AppKit window\n";
    static const char fail_create[] =
        "HRT M6 GUEST FAIL: CREATE did not return a window handle\n";
    static const char fail_query[] =
        "HRT M6 GUEST FAIL: AppKit window did not cross the visibility gate\n";
    static const char fail_capture[] =
        "HRT M6 GUEST FAIL: AppKit window capture failed\n";

    int64_t handle = host_call(
        HRT_M6_OP_CREATE_WINDOW,
        (uint64_t)(uintptr_t)title, UINT64_C(720), UINT64_C(460), 0u, 0u);
    if (handle <= 0) {
        write_bytes(fail_create, sizeof(fail_create) - 1u);
        write_status(handle, 0, 0);
        terminate(10);
    }

    (void)host_call(HRT_M6_OP_PUMP_EVENTS, UINT64_C(700), 0u, 0u, 0u, 0u);
    int64_t flags = host_call(HRT_M6_OP_QUERY_WINDOW,
                              (uint64_t)handle, 0u, 0u, 0u, 0u);
    const uint64_t required = HRT_M6_WINDOW_ALLOCATED |
                              HRT_M6_WINDOW_VISIBLE |
                              HRT_M6_WINDOW_SERVER_LISTED |
                              HRT_M6_SCREEN_AVAILABLE |
                              HRT_M6_ON_MAIN_THREAD;
    if (flags < 0 || (((uint64_t)flags & required) != required)) {
        write_bytes(fail_query, sizeof(fail_query) - 1u);
        write_status(handle, flags, 0);
        (void)host_call(HRT_M6_OP_DESTROY_WINDOW,
                        (uint64_t)handle, 0u, 0u, 0u, 0u);
        terminate(11);
    }

    int64_t capture = host_call(HRT_M6_OP_CAPTURE_WINDOW,
                                (uint64_t)handle, 0u, 0u, 0u, 0u);
    write_status(handle, flags, capture);
    if (capture != 1) {
        write_bytes(fail_capture, sizeof(fail_capture) - 1u);
        (void)host_call(HRT_M6_OP_DESTROY_WINDOW,
                        (uint64_t)handle, 0u, 0u, 0u, 0u);
        terminate(12);
    }

    write_bytes(pass, sizeof(pass) - 1u);
    (void)host_call(HRT_M6_OP_PUMP_EVENTS, UINT64_C(250), 0u, 0u, 0u, 0u);
    (void)host_call(HRT_M6_OP_DESTROY_WINDOW,
                    (uint64_t)handle, 0u, 0u, 0u, 0u);
    terminate(0);
}
