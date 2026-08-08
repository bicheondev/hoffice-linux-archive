#!/usr/bin/env python3
"""Add the GLib eventfd2 subset after the mature directory/epoll bridge.

The older M3 eventfd transform deliberately skipped mature bridges because
close(2) was already owned by deterministic directory and epoll state.  Exact
HWord consequently retained one ENOSYS 290 probe.  This transform integrates a
pipe-backed eventfd table with all three owners instead of replacing them:

* eventfd2(0, EFD_NONBLOCK|EFD_CLOEXEC) returns a real pollable read fd;
* 8-byte guest writes are redirected to the retained pipe write fd;
* 8-byte guest reads consume the wakeup value; and
* close tears down both pipe ends after epoll and directory bookkeeping.

The implementation is intentionally limited to GLib's single-pending-wakeup
usage.  EFD_SEMAPHORE and unknown flags fail with EINVAL.  Every edit is
exact-anchor and fail-closed.
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
    if "M10 mature eventfd2" in text:
        raise SystemExit("mature eventfd2 compatibility is already present")

    text = replace_once(
        text,
        "#ifndef LINUX_SYS_PIPE2\n"
        "#define LINUX_SYS_PIPE2 UINT64_C(293)\n"
        "#endif\n",
        "#ifndef LINUX_SYS_EVENTFD2\n"
        "#define LINUX_SYS_EVENTFD2 UINT64_C(290)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_PIPE2\n"
        "#define LINUX_SYS_PIPE2 UINT64_C(293)\n"
        "#endif\n"
        "#define M10_LINUX_EFD_SEMAPHORE UINT64_C(0x1)\n"
        "#define M10_LINUX_EFD_NONBLOCK UINT64_C(0x800)\n"
        "#define M10_LINUX_EFD_CLOEXEC UINT64_C(0x80000)\n",
        "mature eventfd2 constants",
    )

    bridge = r'''
#define M10_MAX_EVENTFDS 64u
#define M10_EVENTFD_TRACE_LIMIT 32u

/* M10 mature eventfd2: coexists with directory-stream and epoll close state. */
typedef struct {
    int read_fd;
    int write_fd;
    int active;
} M10Eventfd;

static M10Eventfd g_m10_eventfds[M10_MAX_EVENTFDS];
static unsigned int g_m10_eventfd_trace_count;

static M10Eventfd *m10_find_eventfd(int fd) {
    for (size_t index = 0u; index < M10_MAX_EVENTFDS; ++index) {
        if (g_m10_eventfds[index].active &&
            g_m10_eventfds[index].read_fd == fd) {
            return &g_m10_eventfds[index];
        }
    }
    return NULL;
}

static M10Eventfd *m10_allocate_eventfd(void) {
    for (size_t index = 0u; index < M10_MAX_EVENTFDS; ++index) {
        if (!g_m10_eventfds[index].active)
            return &g_m10_eventfds[index];
    }
    return NULL;
}

static void m10_trace_eventfd(const char *stage, int64_t result,
                              uint64_t initial_value, uint64_t flags,
                              int read_fd, int write_fd) {
    if (g_m10_eventfd_trace_count >= M10_EVENTFD_TRACE_LIMIT) return;
    ++g_m10_eventfd_trace_count;
    char buffer[320];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M10 EVENTFD: stage=");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), stage);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " result=");
    if (result < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-result));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)result);
    }
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " initial=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), initial_value);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " flags=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), flags);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " read-fd=");
    if (read_fd < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-(int64_t)read_fd));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(unsigned int)read_fd);
    }
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " write-fd=");
    if (write_fd < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-(int64_t)write_fd));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(unsigned int)write_fd);
    }
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static int64_t m10_host_eventfd2_bridge(uint64_t initial_value,
                                        uint64_t linux_flags) {
    const uint64_t supported =
        M10_LINUX_EFD_NONBLOCK | M10_LINUX_EFD_CLOEXEC;
    if ((linux_flags & M10_LINUX_EFD_SEMAPHORE) != 0u ||
        (linux_flags & ~supported) != 0u || initial_value > UINT32_MAX) {
        m10_trace_eventfd("reject", -LINUX_EINVAL, initial_value,
                          linux_flags, -1, -1);
        return -LINUX_EINVAL;
    }

    M10Eventfd *entry = m10_allocate_eventfd();
    if (entry == NULL) {
        m10_trace_eventfd("capacity", -LINUX_EMFILE, initial_value,
                          linux_flags, -1, -1);
        return -LINUX_EMFILE;
    }

    int descriptors[2] = {-1, -1};
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int host_result = pipe(descriptors);
    int saved_errno = errno;
    if (host_result == 0 &&
        (set_pipe_descriptor_flags(descriptors[0], linux_flags) != 0 ||
         set_pipe_descriptor_flags(descriptors[1], linux_flags) != 0)) {
        saved_errno = errno;
        (void)close(descriptors[0]);
        (void)close(descriptors[1]);
        descriptors[0] = -1;
        descriptors[1] = -1;
        host_result = -1;
    }
    if (host_result == 0 && initial_value != 0u) {
        uint64_t value = initial_value;
        ssize_t written = write(descriptors[1], &value, sizeof(value));
        if (written != (ssize_t)sizeof(value)) {
            saved_errno = written < 0 ? errno : EIO;
            (void)close(descriptors[0]);
            (void)close(descriptors[1]);
            descriptors[0] = -1;
            descriptors[1] = -1;
            host_result = -1;
        }
    }
    restore_guest_context(guest);

    if (host_result != 0) {
        int64_t result = -(int64_t)linux_errno_from_host(saved_errno);
        m10_trace_eventfd("create-error", result, initial_value,
                          linux_flags, descriptors[0], descriptors[1]);
        return result;
    }

    entry->read_fd = descriptors[0];
    entry->write_fd = descriptors[1];
    entry->active = 1;
    m10_trace_eventfd("created", entry->read_fd, initial_value,
                      linux_flags, entry->read_fd, entry->write_fd);
    return entry->read_fd;
}

static int64_t m10_host_eventfd_read(M10Eventfd *entry,
                                     void *buffer, size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (size != sizeof(uint64_t)) return -LINUX_EINVAL;
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    ssize_t host_result = read(entry->read_fd, buffer, sizeof(uint64_t));
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)host_result, saved_errno);
}

static int64_t m10_host_eventfd_write(M10Eventfd *entry,
                                      const void *buffer, size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (size != sizeof(uint64_t)) return -LINUX_EINVAL;
    uint64_t value;
    memcpy(&value, buffer, sizeof(value));
    if (value == UINT64_MAX) return -LINUX_EINVAL;

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    ssize_t host_result = write(entry->write_fd, &value, sizeof(value));
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)host_result, saved_errno);
}

static int m10_close_eventfd_if_present(int fd, int *saved_errno) {
    M10Eventfd *entry = m10_find_eventfd(fd);
    if (entry == NULL) return 0;

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int read_result = close(entry->read_fd);
    int first_errno = errno;
    errno = 0;
    int write_result = close(entry->write_fd);
    int second_errno = errno;
    restore_guest_context(guest);

    entry->read_fd = -1;
    entry->write_fd = -1;
    entry->active = 0;
    if (read_result != 0) {
        *saved_errno = first_errno;
        return -1;
    }
    if (write_result != 0) {
        *saved_errno = second_errno;
        return -1;
    }
    return 1;
}

'''
    text = replace_once(
        text,
        "static int64_t host_read_bridge(int fd, void *buffer, size_t size) {\n",
        bridge
        + "static int64_t host_read_bridge(int fd, void *buffer, size_t size) {\n"
        + "    M10Eventfd *eventfd = m10_find_eventfd(fd);\n"
        + "    if (eventfd != NULL)\n"
        + "        return m10_host_eventfd_read(eventfd, buffer, size);\n",
        "eventfd table and read interception",
    )

    text = replace_once(
        text,
        "static int64_t host_write_bridge(int fd, const void *buffer, size_t size) {\n"
        "    uintptr_t guest = switch_to_host_context();\n",
        "static int64_t host_write_bridge(int fd, const void *buffer, size_t size) {\n"
        "    M10Eventfd *eventfd = m10_find_eventfd(fd);\n"
        "    if (eventfd != NULL)\n"
        "        return m10_host_eventfd_write(eventfd, buffer, size);\n"
        "    uintptr_t guest = switch_to_host_context();\n",
        "eventfd write interception",
    )

    close_anchor = '''static int64_t host_close_bridge(int fd) {
    forget_epoll_state(fd);
    forget_directory_stream(fd);
    uintptr_t guest = switch_to_host_context();
'''
    close_replacement = '''static int64_t host_close_bridge(int fd) {
    forget_epoll_state(fd);
    forget_directory_stream(fd);
    int eventfd_errno = 0;
    int eventfd_result = m10_close_eventfd_if_present(fd, &eventfd_errno);
    if (eventfd_result != 0) {
        return eventfd_result > 0 ? 0 :
            -(int64_t)linux_errno_from_host(eventfd_errno);
    }
    uintptr_t guest = switch_to_host_context();
'''
    text = replace_once(text, close_anchor, close_replacement,
                        "cooperative eventfd close interception")

    text = replace_once(
        text,
        "        case LINUX_SYS_PIPE2:\n"
        "            result = host_pipe2_bridge(\n",
        "        case LINUX_SYS_EVENTFD2:\n"
        "            result = m10_host_eventfd2_bridge(\n"
        "                state->__rdi, state->__rsi);\n"
        "            break;\n"
        "        case LINUX_SYS_PIPE2:\n"
        "            result = host_pipe2_bridge(\n",
        "mature eventfd2 dispatch",
    )

    required = {
        "case LINUX_SYS_EVENTFD2:": 1,
        "m10_host_eventfd2_bridge(": 2,
        "m10_host_eventfd_read(": 2,
        "m10_host_eventfd_write(": 2,
        "m10_close_eventfd_if_present(": 2,
        "M10 mature eventfd2": 1,
        "HRT M10 EVENTFD:": 1,
        "forget_epoll_state(fd);": 1,
        "forget_directory_stream(fd);": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"eventfd marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
