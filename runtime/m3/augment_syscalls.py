#!/usr/bin/env python3
"""Generate the M3 syscall bridge with incremental Linux ABI handlers.

The large signal bridge stays readable while new syscall coverage is iterated in
small, reviewable augmentations.  Every insertion is anchored and fail-closed so
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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
