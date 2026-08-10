#!/usr/bin/env python3
"""Add the Linux x86-64 ``sendfile`` boundary used by HWord startup.

Exact HWord replays still report syscall 40 twice before the native document
validation dialog.  Returning ``ENOSYS`` can break an otherwise successful
resource or template transfer.  This transform implements the Linux ABI in the
clean-room host without modifying the guest binary.

The bridge uses bounded 16 KiB chunks.  Seekable inputs are copied with
``pread`` so a partial output write never consumes unreported input bytes; the
input descriptor position is advanced explicitly when Linux supplies a null
offset pointer.  Non-seekable inputs fall back to ``read``.  A non-null Linux
offset pointer is updated only by bytes successfully written.  Host libc calls
run only after restoring the Darwin pthread/TSD GS base, and a bounded trace
records each observed transfer.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M11 SENDFILE:" in text:
        raise SystemExit("M11 sendfile compatibility is already present")

    constant_anchor = '''#ifndef LINUX_SYS_CLOCK_NANOSLEEP
#define LINUX_SYS_CLOCK_NANOSLEEP UINT64_C(230)
#endif
#define M11_LINUX_TIMER_ABSTIME UINT64_C(1)
'''
    constant_replacement = constant_anchor + '''#ifndef LINUX_SYS_SENDFILE
#define LINUX_SYS_SENDFILE UINT64_C(40)
#endif
#define M11_SENDFILE_BUFFER_BYTES 16384u
#define M11_SENDFILE_TRACE_LIMIT 32u
'''
    text = replace_once(text, constant_anchor, constant_replacement,
                        "sendfile constants")

    helper_anchor = '''static int64_t bridge_gettimeofday(LinuxTimeval *guest_time) {
'''
    helpers = r'''static unsigned int g_m11_sendfile_trace_count;

static void m11_trace_sendfile(int output_fd, int input_fd,
                               const int64_t *guest_offset,
                               uint64_t requested, int64_t result,
                               int seekable_input) {
    if (g_m11_sendfile_trace_count >= M11_SENDFILE_TRACE_LIMIT)
        return;
    ++g_m11_sendfile_trace_count;
    char buffer[384];
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
                                  guest_offset != NULL ? 1u : 0u);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " seekable=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  seekable_input ? 1u : 0u);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " requested=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), requested);
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

static int64_t m11_sendfile_error_or_partial(int saved_errno,
                                             uint64_t transferred) {
    if (transferred != 0u)
        return transferred > (uint64_t)INT64_MAX
            ? INT64_MAX : (int64_t)transferred;
    return -(int64_t)linux_errno_from_host(saved_errno);
}

static int64_t bridge_sendfile(int output_fd, int input_fd,
                               int64_t *guest_offset, size_t count) {
    if (output_fd < 0 || input_fd < 0 || output_fd == input_fd)
        return -LINUX_EINVAL;
    if (count == 0u) {
        m11_trace_sendfile(output_fd, input_fd, guest_offset, 0u, 0, 0);
        return 0;
    }

    int64_t cursor_offset = 0;
    int seekable_input = 0;
    if (guest_offset != NULL) {
        cursor_offset = *guest_offset;
        if (cursor_offset < 0)
            return -LINUX_EINVAL;
        seekable_input = 1;
    } else {
        uintptr_t guest_context = switch_to_host_context();
        errno = 0;
        const off_t current = lseek(input_fd, (off_t)0, SEEK_CUR);
        const int saved_errno = errno;
        restore_guest_context(guest_context);
        if (current >= 0) {
            cursor_offset = (int64_t)current;
            seekable_input = 1;
        } else if (saved_errno != ESPIPE) {
            const int64_t result = -(int64_t)linux_errno_from_host(saved_errno);
            m11_trace_sendfile(output_fd, input_fd, guest_offset,
                               (uint64_t)count, result, 0);
            return result;
        }
    }

    unsigned char transfer_buffer[M11_SENDFILE_BUFFER_BYTES];
    uint64_t transferred = 0u;
    int terminal_errno = 0;

    while (transferred < (uint64_t)count) {
        const uint64_t remaining = (uint64_t)count - transferred;
        const size_t requested = remaining < M11_SENDFILE_BUFFER_BYTES
            ? (size_t)remaining : M11_SENDFILE_BUFFER_BYTES;

        ssize_t read_result = -1;
        int read_errno = 0;
        for (;;) {
            uintptr_t guest_context = switch_to_host_context();
            errno = 0;
            if (seekable_input) {
                read_result = pread(input_fd, transfer_buffer, requested,
                                    (off_t)cursor_offset);
            } else {
                read_result = read(input_fd, transfer_buffer, requested);
            }
            read_errno = errno;
            restore_guest_context(guest_context);
            if (read_result < 0 && read_errno == EINTR)
                continue;
            break;
        }

        if (read_result == 0)
            break;
        if (read_result < 0) {
            terminal_errno = read_errno;
            break;
        }

        size_t written = 0u;
        while (written < (size_t)read_result) {
            ssize_t write_result = -1;
            int write_errno = 0;
            for (;;) {
                uintptr_t guest_context = switch_to_host_context();
                errno = 0;
                write_result = write(output_fd, transfer_buffer + written,
                                     (size_t)read_result - written);
                write_errno = errno;
                restore_guest_context(guest_context);
                if (write_result < 0 && write_errno == EINTR)
                    continue;
                break;
            }
            if (write_result <= 0) {
                terminal_errno = write_result == 0 ? EIO : write_errno;
                break;
            }
            written += (size_t)write_result;
            transferred += (uint64_t)write_result;
            cursor_offset += (int64_t)write_result;
            if (guest_offset != NULL)
                *guest_offset = cursor_offset;
        }

        if (guest_offset == NULL && seekable_input) {
            uintptr_t guest_context = switch_to_host_context();
            errno = 0;
            const off_t positioned = lseek(
                input_fd, (off_t)cursor_offset, SEEK_SET);
            const int position_errno = errno;
            restore_guest_context(guest_context);
            if (positioned < 0) {
                terminal_errno = position_errno;
                break;
            }
        } else if (!seekable_input && written < (size_t)read_result) {
            /* A non-seekable read consumed more than the output accepted.
             * Linux may report the successful prefix; no portable rewind is
             * available for this uncommon file-to-pipe failure path. */
            break;
        }

        if (written < (size_t)read_result || terminal_errno != 0)
            break;
    }

    const int64_t result = terminal_errno != 0
        ? m11_sendfile_error_or_partial(terminal_errno, transferred)
        : (transferred > (uint64_t)INT64_MAX
            ? INT64_MAX : (int64_t)transferred);
    m11_trace_sendfile(output_fd, input_fd, guest_offset,
                       (uint64_t)count, result, seekable_input);
    return result;
}

static int64_t bridge_gettimeofday(LinuxTimeval *guest_time) {
'''
    text = replace_once(text, helper_anchor, helpers,
                        "sendfile bridge insertion")

    dispatch_anchor = '''        case LINUX_SYS_CLOCK_NANOSLEEP:
            result = bridge_clock_nanosleep(
                (int)state->__rdi, state->__rsi,
                (const LinuxTimespec *)(uintptr_t)state->__rdx,
                (LinuxTimespec *)(uintptr_t)state->__r10);
            break;
        case LINUX_SYS_OPENAT:
'''
    dispatch_replacement = '''        case LINUX_SYS_CLOCK_NANOSLEEP:
            result = bridge_clock_nanosleep(
                (int)state->__rdi, state->__rsi,
                (const LinuxTimespec *)(uintptr_t)state->__rdx,
                (LinuxTimespec *)(uintptr_t)state->__r10);
            break;
        case LINUX_SYS_SENDFILE:
            result = bridge_sendfile(
                (int)state->__rdi, (int)state->__rsi,
                (int64_t *)(uintptr_t)state->__rdx,
                (size_t)state->__r10);
            break;
        case LINUX_SYS_OPENAT:
'''
    text = replace_once(text, dispatch_anchor, dispatch_replacement,
                        "sendfile dispatch")

    required = {
        "HRT M11 SENDFILE:": 1,
        "LINUX_SYS_SENDFILE": 3,
        "M11_SENDFILE_BUFFER_BYTES 16384u": 2,
        "M11_SENDFILE_TRACE_LIMIT 32u": 2,
        "bridge_sendfile(": 2,
        "case LINUX_SYS_SENDFILE:": 1,
        "pread(input_fd": 1,
        "lseek(input_fd": 1,
        "write(output_fd": 1,
        "switch_to_host_context()": 4,
        "restore_guest_context(guest_context);": 4,
        "*guest_offset = cursor_offset": 1,
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
