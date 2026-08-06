#!/usr/bin/env python3
"""Inject Linux x86-64 pipe2 support into the generated M3 bridge.

GLib first probes eventfd2 and then falls back to pipe2 for GWakeup.  This
bridge intentionally leaves eventfd2 as ENOSYS and provides the documented
pipe fallback with Linux O_NONBLOCK and O_CLOEXEC semantics.
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
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n",
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n"
        "#ifndef LINUX_SYS_PIPE2\n"
        "#define LINUX_SYS_PIPE2 UINT64_C(293)\n"
        "#endif\n",
        "pipe2 syscall constant",
    )

    bridge = r'''
static int set_pipe_descriptor_flags(int fd, uint64_t linux_flags) {
    if ((linux_flags & LINUX_O_CLOEXEC) != 0u) {
        if (fcntl(fd, F_SETFD, FD_CLOEXEC) != 0) return -1;
    }
    if ((linux_flags & LINUX_O_NONBLOCK) != 0u) {
        int current = fcntl(fd, F_GETFL, 0);
        if (current < 0) return -1;
        if (fcntl(fd, F_SETFL, current | O_NONBLOCK) != 0) return -1;
    }
    return 0;
}

static int64_t host_pipe2_bridge(int *guest_descriptors,
                                 uint64_t linux_flags) {
    if (guest_descriptors == NULL) return -LINUX_EFAULT;
    const uint64_t supported = LINUX_O_CLOEXEC | LINUX_O_NONBLOCK;
    if ((linux_flags & ~supported) != 0u) return -LINUX_EINVAL;

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
    restore_guest_context(guest);

    if (result != 0) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }
    guest_descriptors[0] = descriptors[0];
    guest_descriptors[1] = descriptors[1];
    return 0;
}

'''
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        bridge + "static int64_t host_close_bridge(int fd) {\n",
        "pipe2 bridge",
    )

    text = replace_once(
        text,
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "        case LINUX_SYS_PIPE2:\n"
        "            result = host_pipe2_bridge(\n"
        "                (int *)(uintptr_t)state->__rdi, state->__rsi);\n"
        "            break;\n"
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "pipe2 dispatch",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
