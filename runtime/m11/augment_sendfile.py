#!/usr/bin/env python3
"""Add the Linux x86-64 ``sendfile`` boundary to the host bridge.

The exact HWord document replay repeatedly reaches syscall 40.  Returning
``ENOSYS`` is no longer an acceptable compatibility boundary once document
construction begins because HWord and its support libraries may use sendfile
for template or package transport.

This transform implements Linux ``sendfile(out_fd, in_fd, offset, count)``
without modifying any guest ELF:

* an explicit guest offset uses host ``pread`` and is advanced only by bytes
  successfully written;
* a null offset uses host ``read`` and therefore advances the input descriptor;
* a partial output failure rewinds unread input bytes for seekable descriptors;
* partial progress is returned ahead of a later host error, matching Linux
  short-transfer behavior;
* every Darwin libc operation executes with the host pthread/TSD GS restored;
* work is bounded to an 8 KiB signal-stack buffer; and
* the first 32 calls emit a compact ``HRT M11 SENDFILE`` trace.

The edit is exact and fail closed.  It expects the mature POSIX and timing
composition used by the current HWord host.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M11 SENDFILE:" in text:
        raise SystemExit("M11 sendfile compatibility is already present")

    constants_anchor = '''#ifndef LINUX_SYS_CLOCK_NANOSLEEP
#define LINUX_SYS_CLOCK_NANOSLEEP UINT64_C(230)
#endif
#define M11_LINUX_TIMER_ABSTIME UINT64_C(1)
'''
    constants_replacement = '''#ifndef LINUX_SYS_CLOCK_NANOSLEEP
#define LINUX_SYS_CLOCK_NANOSLEEP UINT64_C(230)
#endif
#ifndef LINUX_SYS_SENDFILE
#define LINUX_SYS_SENDFILE UINT64_C(40)
#endif
#define M11_LINUX_TIMER_ABSTIME UINT64_C(1)
'''
    text = replace_once(text, constants_anchor, constants_replacement,
                        "sendfile syscall constant")

    helper_anchor = '''static int64_t bridge_clock_nanosleep(
'''
    helper = r'''#define M11_SENDFILE_CHUNK 8192u
#define M11_SENDFILE_TRACE_LIMIT 32u

static unsigned int g_m11_sendfile_trace_count;

static void m11_trace_sendfile(int output_fd, int input_fd,
                               const int64_t *offset, uint64_t count,
                               int64_t result) {
    if (g_m11_sendfile_trace_count >= M11_SENDFILE_TRACE_LIMIT)
        return;
    ++g_m11_sendfile_trace_count;
    char buffer[320];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M11 SENDFILE: out=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)output_fd);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " in=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)input_fd);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " explicit-offset=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  offset != NULL ? 1u : 0u);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " offset=");
    if (offset != NULL && *offset < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(
            buffer, cursor, sizeof(buffer),
            (uint64_t)(-(*offset + 1)) + UINT64_C(1));
    } else {
        cursor = trace_append_decimal(
            buffer, cursor, sizeof(buffer),
            offset != NULL ? (uint64_t)*offset : 0u);
    }
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " count=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), count);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " result=");
    if (result < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-result));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)result);
    }
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static ssize_t m11_host_read_for_sendfile(int fd, void *buffer, size_t size,
                                          int64_t offset,
                                          int explicit_offset,
                                          int *saved_errno) {
    uintptr_t guest_context = switch_to_host_context();
    errno = 0;
    const ssize_t result = explicit_offset
        ? pread(fd, buffer, size, (off_t)offset)
        : read(fd, buffer, size);
    if (saved_errno != NULL) *saved_errno = errno;
    restore_guest_context(guest_context);
    return result;
}

static ssize_t m11_host_write_for_sendfile(int fd, const void *buffer,
                                           size_t size, int *saved_errno) {
    uintptr_t guest_context = switch_to_host_context();
    errno = 0;
    const ssize_t result = write(fd, buffer, size);
    if (saved_errno != NULL) *saved_errno = errno;
    restore_guest_context(guest_context);
    return result;
}

static void m11_rewind_sendfile_input(int fd, uint64_t byte_count) {
    if (byte_count == 0u || byte_count > (uint64_t)INT64_MAX)
        return;
    uintptr_t guest_context = switch_to_host_context();
    (void)lseek(fd, (off_t)-(int64_t)byte_count, SEEK_CUR);
    restore_guest_context(guest_context);
}

static int64_t bridge_sendfile(int output_fd, int input_fd,
                               int64_t *guest_offset, uint64_t count) {
    if (count == 0u) {
        m11_trace_sendfile(output_fd, input_fd, guest_offset, count, 0);
        return 0;
    }

    const int explicit_offset = guest_offset != NULL;
    int64_t logical_offset = explicit_offset ? *guest_offset : 0;
    if (explicit_offset && logical_offset < 0) {
        m11_trace_sendfile(output_fd, input_fd, guest_offset, count,
                           -LINUX_EINVAL);
        return -LINUX_EINVAL;
    }

    const uint64_t transfer_limit = count > (uint64_t)INT64_MAX
        ? (uint64_t)INT64_MAX : count;
    uint64_t total = 0u;
    unsigned char buffer[M11_SENDFILE_CHUNK];

    while (total < transfer_limit) {
        const uint64_t remaining = transfer_limit - total;
        const size_t request = remaining < M11_SENDFILE_CHUNK
            ? (size_t)remaining : M11_SENDFILE_CHUNK;
        int saved_errno = 0;
        const ssize_t read_result = m11_host_read_for_sendfile(
            input_fd, buffer, request, logical_offset,
            explicit_offset, &saved_errno);
        if (read_result < 0) {
            const int64_t failure =
                -(int64_t)linux_errno_from_host(saved_errno);
            const int64_t result = total != 0u ? (int64_t)total : failure;
            m11_trace_sendfile(output_fd, input_fd, guest_offset,
                               count, result);
            return result;
        }
        if (read_result == 0)
            break;

        size_t written = 0u;
        while (written < (size_t)read_result) {
            saved_errno = 0;
            const ssize_t write_result = m11_host_write_for_sendfile(
                output_fd, buffer + written,
                (size_t)read_result - written, &saved_errno);
            if (write_result <= 0) {
                const uint64_t unsent =
                    (uint64_t)((size_t)read_result - written);
                if (!explicit_offset)
                    m11_rewind_sendfile_input(input_fd, unsent);
                if (explicit_offset) {
                    logical_offset += (int64_t)written;
                    *guest_offset = logical_offset;
                }
                total += (uint64_t)written;
                const int host_error = write_result == 0 ? EIO : saved_errno;
                const int64_t failure =
                    -(int64_t)linux_errno_from_host(host_error);
                const int64_t result = total != 0u
                    ? (int64_t)total : failure;
                m11_trace_sendfile(output_fd, input_fd, guest_offset,
                                   count, result);
                return result;
            }
            written += (size_t)write_result;
        }

        total += (uint64_t)written;
        if (explicit_offset) {
            logical_offset += (int64_t)written;
            *guest_offset = logical_offset;
        }
    }

    const int64_t result = (int64_t)total;
    m11_trace_sendfile(output_fd, input_fd, guest_offset, count, result);
    return result;
}

static int64_t bridge_clock_nanosleep(
'''
    text = replace_once(text, helper_anchor, helper,
                        "sendfile bridge insertion")

    dispatch_anchor = '''        case LINUX_SYS_CLOCK_NANOSLEEP:
            result = bridge_clock_nanosleep(
'''
    dispatch_replacement = '''        case LINUX_SYS_SENDFILE:
            result = bridge_sendfile(
                (int)state->__rdi, (int)state->__rsi,
                (int64_t *)(uintptr_t)state->__rdx, state->__r10);
            break;
        case LINUX_SYS_CLOCK_NANOSLEEP:
            result = bridge_clock_nanosleep(
'''
    text = replace_once(text, dispatch_anchor, dispatch_replacement,
                        "sendfile syscall dispatch")

    required = {
        "HRT M11 SENDFILE:": 1,
        "LINUX_SYS_SENDFILE": 3,
        "M11_SENDFILE_CHUNK 8192u": 1,
        "bridge_sendfile(": 2,
        "m11_host_read_for_sendfile(": 2,
        "m11_host_write_for_sendfile(": 2,
        "m11_rewind_sendfile_input(": 2,
        "case LINUX_SYS_SENDFILE:": 1,
        "*guest_offset = logical_offset;": 2,
        "pread(fd, buffer, size": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"sendfile marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
