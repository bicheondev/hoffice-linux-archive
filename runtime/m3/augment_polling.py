#!/usr/bin/env python3
"""Inject Linux x86-64 poll and ppoll support into an M3 bridge.

Darwin and Linux use the same pollfd layout and the core event bits used by
GLib/Qt.  The bridge therefore calls the host poll implementation directly
while the host GS context is active.  ppoll is supported for the common
NULL-signal-mask form and converts a Linux timespec to a millisecond timeout.
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

    if "host_poll_bridge(" in text:
        raise SystemExit("poll bridge is already present")

    if "#include <poll.h>\n" not in text:
        text = replace_once(
            text,
            "#include <limits.h>\n",
            "#include <limits.h>\n#include <poll.h>\n",
            "poll include",
        )

    text = replace_once(
        text,
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n",
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n"
        "#ifndef LINUX_SYS_POLL\n"
        "#define LINUX_SYS_POLL UINT64_C(7)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_PPOLL\n"
        "#define LINUX_SYS_PPOLL UINT64_C(271)\n"
        "#endif\n",
        "poll syscall constants",
    )

    bridge = r'''
struct M3LinuxTimespec {
    int64_t seconds;
    int64_t nanoseconds;
};

_Static_assert(sizeof(struct pollfd) == 8u,
               "Darwin pollfd must match Linux x86-64");
_Static_assert(offsetof(struct pollfd, events) == 4u,
               "Darwin pollfd.events offset must match Linux x86-64");
_Static_assert(offsetof(struct pollfd, revents) == 6u,
               "Darwin pollfd.revents offset must match Linux x86-64");

static int64_t host_poll_bridge(struct pollfd *descriptors,
                                uint64_t descriptor_count,
                                int timeout_milliseconds) {
    if (descriptor_count > (uint64_t)UINT_MAX) return -LINUX_EINVAL;
    if (descriptor_count != 0u && descriptors == NULL) return -LINUX_EFAULT;

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result = poll(descriptors, (nfds_t)descriptor_count,
                      timeout_milliseconds);
    int saved_errno = errno;
    restore_guest_context(guest);
    if (result < 0) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }
    return (int64_t)result;
}

static int linux_timespec_to_poll_timeout(
    const struct M3LinuxTimespec *timeout, int *milliseconds_out) {
    if (timeout == NULL) {
        *milliseconds_out = -1;
        return 0;
    }
    if (timeout->seconds < 0 || timeout->nanoseconds < 0 ||
        timeout->nanoseconds >= INT64_C(1000000000)) {
        return -LINUX_EINVAL;
    }

    uint64_t seconds = (uint64_t)timeout->seconds;
    uint64_t milliseconds;
    if (seconds > (uint64_t)INT_MAX / 1000u) {
        milliseconds = (uint64_t)INT_MAX;
    } else {
        milliseconds = seconds * 1000u;
        uint64_t fractional =
            ((uint64_t)timeout->nanoseconds + UINT64_C(999999)) /
            UINT64_C(1000000);
        if (fractional > (uint64_t)INT_MAX - milliseconds) {
            milliseconds = (uint64_t)INT_MAX;
        } else {
            milliseconds += fractional;
        }
    }
    *milliseconds_out = (int)milliseconds;
    return 0;
}

static int64_t host_ppoll_bridge(
    struct pollfd *descriptors, uint64_t descriptor_count,
    const struct M3LinuxTimespec *timeout,
    const void *linux_signal_mask, uint64_t signal_mask_size) {
    (void)signal_mask_size;
    if (linux_signal_mask != NULL) {
        /* Signal-mask translation is deliberately fail-closed for now. */
        return -LINUX_EINVAL;
    }
    int milliseconds = -1;
    int conversion = linux_timespec_to_poll_timeout(timeout, &milliseconds);
    if (conversion != 0) return conversion;
    return host_poll_bridge(descriptors, descriptor_count, milliseconds);
}

'''
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        bridge + "static int64_t host_close_bridge(int fd) {\n",
        "poll bridges",
    )

    text = replace_once(
        text,
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "        case LINUX_SYS_POLL:\n"
        "            result = host_poll_bridge(\n"
        "                (struct pollfd *)(uintptr_t)state->__rdi,\n"
        "                state->__rsi, (int)state->__rdx);\n"
        "            break;\n"
        "        case LINUX_SYS_PPOLL:\n"
        "            result = host_ppoll_bridge(\n"
        "                (struct pollfd *)(uintptr_t)state->__rdi,\n"
        "                state->__rsi,\n"
        "                (const struct M3LinuxTimespec *)(uintptr_t)state->__rdx,\n"
        "                (const void *)(uintptr_t)state->__r10, state->__r8);\n"
        "            break;\n"
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "poll dispatch",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
