#!/usr/bin/env python3
"""Inject the Linux eventfd2 subset used by GLib's GWakeup into M3.

The exact HWord process requests ``eventfd2(0, EFD_NONBLOCK|EFD_CLOEXEC)``.
Darwin has no eventfd ABI, so the generated bridge exposes the read end of a
nonblocking pipe as the guest descriptor and retains the write end in a small
host-side table.  Guest reads, writes, poll calls, and close calls therefore
observe the wakeup behavior GLib requires while the implementation remains
explicitly narrower than a general counter-accurate eventfd emulator:

* EFD_NONBLOCK and EFD_CLOEXEC are supported.
* EFD_SEMAPHORE and unknown flags fail with EINVAL.
* 8-byte reads and writes are translated; the GLib single-pending-wakeup
  discipline avoids the counter-aggregation difference of a pipe.

Every source edit is anchored exactly once and generation fails closed when a
surrounding bridge changes unexpectedly.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
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

    # The deterministic directory-stream bridge owns close(2)
    # interception, so the older pipe-backed eventfd transform
    # cannot safely splice its cleanup into that function.
    # Exact HWord's proven Qt/GLib path instead uses poll/ppoll
    # plus kqueue-backed epoll and tgkill. Delegate to that chain
    # and leave crash-signal injection to the next workflow stage.
    if (
        "host_getdents64_stream_bridge" in text
        and "host_poll_bridge(" not in text
        and "case LINUX_SYS_EVENTFD2:" not in text
    ):
        scripts = (
            "augment_polling.py",
            "augment_epoll.py",
            "augment_tgkill.py",
        )
        script_directory = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(
            prefix="hrt-mature-loop-"
        ) as temp:
            current = args.source
            for index, script in enumerate(scripts, start=1):
                output = Path(temp) / f"{index}.c"
                subprocess.run(
                    [
                        sys.executable,
                        str(script_directory / script),
                        str(current),
                        str(output),
                    ],
                    check=True,
                )
                current = output
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                current.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        return

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
        "#define LINUX_EFD_SEMAPHORE UINT64_C(0x1)\n"
        "#define LINUX_EFD_NONBLOCK UINT64_C(0x800)\n"
        "#define LINUX_EFD_CLOEXEC UINT64_C(0x80000)\n",
        "eventfd2 constants",
    )

    bridge = r'''
#define M3_MAX_EVENTFDS 64u
#define M3_EVENTFD_TRACE_LIMIT 16u

/* Defined by the pipe2 augmentation later in the generated translation unit. */
static int set_pipe_descriptor_flags(int fd, uint64_t linux_flags);

typedef struct {
    int read_fd;
    int write_fd;
    int active;
} M3Eventfd;

static M3Eventfd g_eventfds[M3_MAX_EVENTFDS];
static unsigned int g_eventfd_trace_count;

static M3Eventfd *find_eventfd(int read_fd) {
    for (size_t index = 0u; index < M3_MAX_EVENTFDS; ++index) {
        if (g_eventfds[index].active &&
            g_eventfds[index].read_fd == read_fd) {
            return &g_eventfds[index];
        }
    }
    return NULL;
}

static M3Eventfd *allocate_eventfd(void) {
    for (size_t index = 0u; index < M3_MAX_EVENTFDS; ++index) {
        if (!g_eventfds[index].active) return &g_eventfds[index];
    }
    return NULL;
}

static void raw_trace_eventfd(const char *stage, uint64_t initial_value,
                              uint64_t flags, int read_fd, int write_fd,
                              int64_t result) {
    if (g_eventfd_trace_count >= M3_EVENTFD_TRACE_LIMIT) return;
    ++g_eventfd_trace_count;
    char buffer[320];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "hrt-m3: Linux eventfd2 bridge stage=");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), stage);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " initial=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  initial_value);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " flags=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), flags);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " read-fd=");
    if (read_fd < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-(int64_t)read_fd));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(unsigned int)read_fd);
    }
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " write-fd=");
    if (write_fd < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-(int64_t)write_fd));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(unsigned int)write_fd);
    }
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
    raw_write_literal(buffer, cursor);
}

static int64_t host_eventfd2_bridge(uint64_t initial_value,
                                    uint64_t linux_flags) {
    const uint64_t supported = LINUX_EFD_NONBLOCK | LINUX_EFD_CLOEXEC;
    if ((linux_flags & LINUX_EFD_SEMAPHORE) != 0u ||
        (linux_flags & ~supported) != 0u ||
        initial_value > UINT32_MAX) {
        raw_trace_eventfd("reject", initial_value, linux_flags, -1, -1,
                          -LINUX_EINVAL);
        return -LINUX_EINVAL;
    }

    M3Eventfd *entry = allocate_eventfd();
    if (entry == NULL) {
        raw_trace_eventfd("capacity", initial_value, linux_flags, -1, -1,
                          -LINUX_EMFILE);
        return -LINUX_EMFILE;
    }

    int descriptors[2] = {-1, -1};
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result = pipe(descriptors);
    int saved_errno = errno;
    if (result == 0 &&
        (set_pipe_descriptor_flags(descriptors[0], linux_flags) != 0 ||
         set_pipe_descriptor_flags(descriptors[1], linux_flags) != 0)) {
        saved_errno = errno;
        (void)close(descriptors[0]);
        (void)close(descriptors[1]);
        descriptors[0] = -1;
        descriptors[1] = -1;
        result = -1;
    }
    if (result == 0 && initial_value != 0u) {
        uint64_t value = initial_value;
        ssize_t written = write(descriptors[1], &value, sizeof(value));
        if (written != (ssize_t)sizeof(value)) {
            saved_errno = written < 0 ? errno : EIO;
            (void)close(descriptors[0]);
            (void)close(descriptors[1]);
            descriptors[0] = -1;
            descriptors[1] = -1;
            result = -1;
        }
    }
    restore_guest_context(guest);

    if (result != 0) {
        int64_t linux_result =
            -(int64_t)linux_errno_from_host(saved_errno);
        raw_trace_eventfd("create-error", initial_value, linux_flags,
                          descriptors[0], descriptors[1], linux_result);
        return linux_result;
    }

    entry->read_fd = descriptors[0];
    entry->write_fd = descriptors[1];
    entry->active = 1;
    raw_trace_eventfd("created", initial_value, linux_flags,
                      entry->read_fd, entry->write_fd, entry->read_fd);
    return entry->read_fd;
}

static int64_t host_eventfd_read(M3Eventfd *entry, void *buffer,
                                 size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (size < sizeof(uint64_t)) return -LINUX_EINVAL;
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    ssize_t result = read(entry->read_fd, buffer, sizeof(uint64_t));
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_eventfd_write(M3Eventfd *entry, const void *buffer,
                                  size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (size != sizeof(uint64_t)) return -LINUX_EINVAL;
    uint64_t value;
    memcpy(&value, buffer, sizeof(value));
    if (value == UINT64_MAX) return -LINUX_EINVAL;

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    ssize_t result = write(entry->write_fd, &value, sizeof(value));
    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int close_eventfd_if_present(int fd, int *saved_errno) {
    M3Eventfd *entry = find_eventfd(fd);
    if (entry == NULL) return 0;

    errno = 0;
    int read_result = close(entry->read_fd);
    int first_errno = errno;
    errno = 0;
    int write_result = close(entry->write_fd);
    int second_errno = errno;
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
        + "    M3Eventfd *eventfd = find_eventfd(fd);\n"
        + "    if (eventfd != NULL) {\n"
        + "        return host_eventfd_read(eventfd, buffer, size);\n"
        + "    }\n",
        "eventfd helpers and read interception",
    )

    text = replace_once(
        text,
        "static int64_t host_write_bridge(int fd, const void *buffer, "
        "size_t size) {\n"
        "    uintptr_t guest = switch_to_host_context();\n",
        "static int64_t host_write_bridge(int fd, const void *buffer, "
        "size_t size) {\n"
        "    M3Eventfd *eventfd = find_eventfd(fd);\n"
        "    if (eventfd != NULL) {\n"
        "        return host_eventfd_write(eventfd, buffer, size);\n"
        "    }\n"
        "    uintptr_t guest = switch_to_host_context();\n",
        "eventfd write interception",
    )

    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n"
        "    uintptr_t guest = switch_to_host_context();\n"
        "    errno = 0;\n"
        "    int result = close(fd);\n",
        "static int64_t host_close_bridge(int fd) {\n"
        "    uintptr_t guest = switch_to_host_context();\n"
        "    errno = 0;\n"
        "    int saved_errno = 0;\n"
        "    int eventfd_result = close_eventfd_if_present(fd, &saved_errno);\n"
        "    if (eventfd_result != 0) {\n"
        "        restore_guest_context(guest);\n"
        "        return eventfd_result > 0 ? 0 :\n"
        "            -(int64_t)linux_errno_from_host(saved_errno);\n"
        "    }\n"
        "    int result = close(fd);\n",
        "eventfd close interception",
    )

    text = replace_once(
        text,
        "    int saved_errno = errno;\n"
        "    restore_guest_context(guest);\n"
        "    return linux_host_result((int64_t)result, saved_errno);\n"
        "}\n\n"
        "static int64_t host_open_bridge",
        "    saved_errno = errno;\n"
        "    restore_guest_context(guest);\n"
        "    return linux_host_result((int64_t)result, saved_errno);\n"
        "}\n\n"
        "static int64_t host_open_bridge",
        "close saved-errno reuse",
    )

    text = replace_once(
        text,
        "        case LINUX_SYS_PIPE2:\n"
        "            result = host_pipe2_bridge(\n"
        "                (int *)(uintptr_t)state->__rdi, state->__rsi);\n"
        "            break;\n",
        "        case LINUX_SYS_EVENTFD2:\n"
        "            result = host_eventfd2_bridge(\n"
        "                state->__rdi, state->__rsi);\n"
        "            break;\n"
        "        case LINUX_SYS_PIPE2:\n"
        "            result = host_pipe2_bridge(\n"
        "                (int *)(uintptr_t)state->__rdi, state->__rsi);\n"
        "            break;\n",
        "eventfd2 dispatch",
    )

    required_counts = {
        "case LINUX_SYS_EVENTFD2:": 1,
        "host_eventfd2_bridge(": 2,
        "host_eventfd_read(": 2,
        "host_eventfd_write(": 2,
        "close_eventfd_if_present(": 2,
        "Linux eventfd2 bridge stage=": 1,
        "static int set_pipe_descriptor_flags(": 2,
    }
    for marker, expected in required_counts.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"injected marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
