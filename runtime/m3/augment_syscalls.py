#!/usr/bin/env python3
"""Generate the M3 syscall bridge with incremental Linux ABI handlers.

The large signal bridge stays readable while new syscall coverage is iterated in
small, reviewable augmentations. Every insertion is anchored and fail-closed so
a source refactor cannot silently produce a partially patched runtime.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '#include <sys/time.h>\n',
        '#include <sys/time.h>\n#include <sys/uio.h>\n',
        "sys/uio include",
    )

    text = replace_once(
        text,
        "#define DARWIN_SYS_EXIT UINT64_C(1)\n"
        "#define DARWIN_SYS_WRITE UINT64_C(4)\n",
        "#define DARWIN_SYS_EXIT UINT64_C(1)\n"
        "#define DARWIN_SYS_READ UINT64_C(3)\n"
        "#define DARWIN_SYS_WRITE UINT64_C(4)\n"
        "#define DARWIN_SYS_OPEN UINT64_C(5)\n"
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n",
        "raw random syscall constants",
    )

    trace_bridge = r'''
#define M3_TRACE_LIMIT 256u
static unsigned int g_trace_logs;

static size_t trace_append_literal(char *buffer, size_t cursor,
                                   size_t capacity,
                                   const char *literal) {
    while (*literal != '\0' && cursor < capacity) {
        buffer[cursor++] = *literal++;
    }
    return cursor;
}

static size_t trace_append_decimal(char *buffer, size_t cursor,
                                   size_t capacity, uint64_t value) {
    char digits[24];
    size_t count = 0u;
    do {
        digits[count++] = (char)('0' + (value % 10u));
        value /= 10u;
    } while (value != 0u && count < sizeof(digits));
    while (count != 0u && cursor < capacity) {
        buffer[cursor++] = digits[--count];
    }
    return cursor;
}

static size_t trace_append_hex(char *buffer, size_t cursor,
                               size_t capacity, uint64_t value) {
    static const char hex[] = "0123456789abcdef";
    if (cursor < capacity) buffer[cursor++] = '0';
    if (cursor < capacity) buffer[cursor++] = 'x';
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned int digit = (unsigned int)((value >> shift) & 0x0fu);
        if (digit != 0u || started || shift == 0) {
            started = 1;
            if (cursor < capacity) buffer[cursor++] = hex[digit];
        }
    }
    return cursor;
}

static void raw_trace_syscall(uint64_t number, uint64_t rip,
                              uint64_t a1, uint64_t a2, uint64_t a3,
                              uint64_t a4, uint64_t a5, uint64_t a6) {
    if (g_trace_logs >= M3_TRACE_LIMIT) return;
    ++g_trace_logs;

    char buffer[256];
    size_t cursor = 0u;
#define APPEND_LITERAL(value) do { \
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), value); \
} while (0)
#define APPEND_HEX(value) do { \
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), value); \
} while (0)
    APPEND_LITERAL("hrt-m3: syscall ");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), number);
    APPEND_LITERAL(" rip="); APPEND_HEX(rip);
    APPEND_LITERAL(" a1="); APPEND_HEX(a1);
    APPEND_LITERAL(" a2="); APPEND_HEX(a2);
    APPEND_LITERAL(" a3="); APPEND_HEX(a3);
    APPEND_LITERAL(" a4="); APPEND_HEX(a4);
    APPEND_LITERAL(" a5="); APPEND_HEX(a5);
    APPEND_LITERAL(" a6="); APPEND_HEX(a6);
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
#undef APPEND_HEX
#undef APPEND_LITERAL
    raw_write_literal(buffer, cursor);
}

'''
    text = replace_once(
        text,
        "__attribute__((noreturn))\nstatic void fail_from_signal",
        trace_bridge + "__attribute__((noreturn))\nstatic void fail_from_signal",
        "bounded syscall trace insertion",
    )

    vector_bridge = r'''
typedef struct {
    void *iov_base;
    size_t iov_len;
} LinuxIovec;

_Static_assert(sizeof(LinuxIovec) == sizeof(struct iovec),
               "Linux and Darwin x86-64 iovec size");
_Static_assert(_Alignof(LinuxIovec) == _Alignof(struct iovec),
               "Linux and Darwin x86-64 iovec alignment");

static int64_t host_vector_io_bridge(int fd, const LinuxIovec *vectors,
                                     int count, int write_operation) {
    if (count < 0 || count > 1024) return -LINUX_EINVAL;
    if (count == 0) return 0;
    if (vectors == NULL) return -LINUX_EFAULT;

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    ssize_t result;
    if (write_operation) {
        result = writev(fd, (const struct iovec *)(const void *)vectors, count);
    } else {
        result = readv(fd, (const struct iovec *)(const void *)vectors, count);
    }
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

'''
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        vector_bridge + "static int64_t host_close_bridge(int fd) {\n",
        "vector bridge insertion",
    )

    safe_random = r'''static int64_t bridge_getrandom(void *buffer, size_t size) {
    if (buffer == NULL && size != 0u) return -LINUX_EFAULT;
    if (size == 0u) return 0;

    static const char path[] = "/dev/urandom";
    int64_t fd = raw_bsd_syscall3(
        DARWIN_SYS_OPEN, (uint64_t)(uintptr_t)path,
        (uint64_t)(O_RDONLY | O_CLOEXEC), 0u);
    if (fd < 0) return -LINUX_EIO;

    size_t completed = 0u;
    while (completed < size) {
        int64_t amount = raw_bsd_syscall3(
            DARWIN_SYS_READ, (uint64_t)fd,
            (uint64_t)(uintptr_t)((unsigned char *)buffer + completed),
            (uint64_t)(size - completed));
        if (amount == -(int64_t)EINTR) continue;
        if (amount <= 0) {
            (void)raw_bsd_syscall3(DARWIN_SYS_CLOSE,
                                   (uint64_t)fd, 0u, 0u);
            return -LINUX_EIO;
        }
        completed += (size_t)amount;
    }
    (void)raw_bsd_syscall3(DARWIN_SYS_CLOSE, (uint64_t)fd, 0u, 0u);
    return (int64_t)completed;
}
'''
    old_random = '''static int64_t bridge_getrandom(void *buffer, size_t size) {
    if (buffer == NULL && size != 0u) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    arc4random_buf(buffer, size);
    restore_guest_context(guest);
    return (int64_t)size;
}
'''
    text = replace_once(
        text,
        old_random,
        safe_random,
        "async-signal-safe getrandom bridge",
    )

    translated_clock = r'''static int translate_linux_clock_id(int linux_clock,
                                    clockid_t *host_clock) {
    switch (linux_clock) {
        case 0: /* Linux CLOCK_REALTIME */
            *host_clock = CLOCK_REALTIME;
            return 0;
        case 1: /* Linux CLOCK_MONOTONIC */
            *host_clock = CLOCK_MONOTONIC;
            return 0;
        case 2: /* Linux CLOCK_PROCESS_CPUTIME_ID */
#ifdef CLOCK_PROCESS_CPUTIME_ID
            *host_clock = CLOCK_PROCESS_CPUTIME_ID;
            return 0;
#else
            return -LINUX_EINVAL;
#endif
        case 3: /* Linux CLOCK_THREAD_CPUTIME_ID */
#ifdef CLOCK_THREAD_CPUTIME_ID
            *host_clock = CLOCK_THREAD_CPUTIME_ID;
            return 0;
#else
            return -LINUX_EINVAL;
#endif
        case 4: /* Linux CLOCK_MONOTONIC_RAW */
#ifdef CLOCK_MONOTONIC_RAW
            *host_clock = CLOCK_MONOTONIC_RAW;
#else
            *host_clock = CLOCK_MONOTONIC;
#endif
            return 0;
        case 5: /* Linux CLOCK_REALTIME_COARSE */
            *host_clock = CLOCK_REALTIME;
            return 0;
        case 6: /* Linux CLOCK_MONOTONIC_COARSE */
            *host_clock = CLOCK_MONOTONIC;
            return 0;
        case 7: /* Linux CLOCK_BOOTTIME */
#ifdef CLOCK_UPTIME_RAW
            *host_clock = CLOCK_UPTIME_RAW;
#else
            *host_clock = CLOCK_MONOTONIC;
#endif
            return 0;
        default:
            return -LINUX_EINVAL;
    }
}

static int64_t bridge_clock_gettime(int clock_id,
                                    LinuxTimespec *guest_time) {
    if (guest_time == NULL) return -LINUX_EFAULT;
    clockid_t host_clock;
    int translation = translate_linux_clock_id(clock_id, &host_clock);
    if (translation != 0) return translation;

    uintptr_t guest = switch_to_host_context();
    struct timespec host_time;
    errno = 0;
    int result = clock_gettime(host_clock, &host_time);
    int saved_errno = errno;
    if (result == 0) {
        guest_time->tv_sec = (int64_t)host_time.tv_sec;
        guest_time->tv_nsec = (int64_t)host_time.tv_nsec;
    }
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}
'''
    old_clock = '''static int64_t bridge_clock_gettime(int clock_id,
                                    LinuxTimespec *guest_time) {
    if (guest_time == NULL) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    struct timespec host_time;
    errno = 0;
    int result = clock_gettime((clockid_t)clock_id, &host_time);
    int saved_errno = errno;
    if (result == 0) {
        guest_time->tv_sec = (int64_t)host_time.tv_sec;
        guest_time->tv_nsec = (int64_t)host_time.tv_nsec;
    }
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}
'''
    text = replace_once(
        text,
        old_clock,
        translated_clock,
        "Linux-to-Darwin clock translation",
    )

    vector_cases = r'''        case LINUX_SYS_READV:
            result = host_vector_io_bridge(
                (int)state->__rdi,
                (const LinuxIovec *)(uintptr_t)state->__rsi,
                (int)state->__rdx, 0);
            break;
        case LINUX_SYS_WRITEV:
            result = host_vector_io_bridge(
                (int)state->__rdi,
                (const LinuxIovec *)(uintptr_t)state->__rsi,
                (int)state->__rdx, 1);
            break;
'''
    text = replace_once(
        text,
        "        case LINUX_SYS_OPEN:\n",
        vector_cases + "        case LINUX_SYS_OPEN:\n",
        "readv/writev switch insertion",
    )

    text = replace_once(
        text,
        "    int64_t result;\n    switch (state->__rax) {\n",
        "    raw_trace_syscall(state->__rax, rip, state->__rdi, state->__rsi,\n"
        "                      state->__rdx, state->__r10, state->__r8,\n"
        "                      state->__r9);\n"
        "    int64_t result;\n    switch (state->__rax) {\n",
        "syscall trace call",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
