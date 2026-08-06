#!/usr/bin/env python3
"""Add small POSIX filesystem, wall-clock, and socket primitives to M3.

These are the next calls exercised by exact HWord after the official offscreen
QPA enters its Qt/GLib startup path.  The transform is deliberately bounded
and fail-closed: paths are rooted through the existing guest-path translator,
socket creation accepts only known Linux type flags, and every source anchor
must match exactly once.
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
        "#include <sys/mman.h>\n",
        "#include <sys/mman.h>\n#include <sys/socket.h>\n",
        "socket header",
    )

    constants = '''#define DARWIN_SYS_CLOSE UINT64_C(6)\n#ifndef LINUX_SYS_SOCKET\n#define LINUX_SYS_SOCKET UINT64_C(41)\n#endif\n#ifndef LINUX_SYS_MKDIR\n#define LINUX_SYS_MKDIR UINT64_C(83)\n#endif\n#ifndef LINUX_SYS_UNLINK\n#define LINUX_SYS_UNLINK UINT64_C(87)\n#endif\n#ifndef LINUX_SYS_TIME\n#define LINUX_SYS_TIME UINT64_C(201)\n#endif\n\n#define LINUX_AF_UNSPEC 0\n#define LINUX_AF_UNIX 1\n#define LINUX_AF_INET 2\n#define LINUX_AF_INET6 10\n#define LINUX_SOCK_TYPE_MASK UINT64_C(0x0f)\n#define LINUX_SOCK_NONBLOCK UINT64_C(0x800)\n#define LINUX_SOCK_CLOEXEC UINT64_C(0x80000)\n\n#ifndef LINUX_EPROTOTYPE\n#define LINUX_EPROTOTYPE 91\n#endif\n#ifndef LINUX_EPROTONOSUPPORT\n#define LINUX_EPROTONOSUPPORT 93\n#endif\n#ifndef LINUX_ESOCKTNOSUPPORT\n#define LINUX_ESOCKTNOSUPPORT 94\n#endif\n#ifndef LINUX_EAFNOSUPPORT\n#define LINUX_EAFNOSUPPORT 97\n#endif\n'''
    text = replace_once(
        text,
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n",
        constants,
        "basic POSIX syscall constants",
    )

    errno_anchor = "        case EOVERFLOW: return LINUX_EOVERFLOW;\n        default: return LINUX_EIO;\n"
    errno_replacement = '''        case EOVERFLOW: return LINUX_EOVERFLOW;
#ifdef EPROTOTYPE
        case EPROTOTYPE: return LINUX_EPROTOTYPE;
#endif
#ifdef EPROTONOSUPPORT
        case EPROTONOSUPPORT: return LINUX_EPROTONOSUPPORT;
#endif
#ifdef ESOCKTNOSUPPORT
        case ESOCKTNOSUPPORT: return LINUX_ESOCKTNOSUPPORT;
#endif
#ifdef EAFNOSUPPORT
        case EAFNOSUPPORT: return LINUX_EAFNOSUPPORT;
#endif
        default: return LINUX_EIO;
'''
    text = replace_once(text, errno_anchor, errno_replacement,
                        "socket errno translation")

    bridge = r'''
#define M3_POSIX_PATH_TRACE_LIMIT 32u
#define M3_SOCKET_TRACE_LIMIT 16u

static unsigned int g_posix_path_trace_count;
static unsigned int g_socket_trace_count;

static void raw_trace_posix_path(const char *operation, const char *host_path,
                                 int64_t result) {
    if (g_posix_path_trace_count >= M3_POSIX_PATH_TRACE_LIMIT) return;
    ++g_posix_path_trace_count;
    char buffer[384];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "hrt-m3: POSIX ");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), operation);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " path=");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), host_path);
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

static void raw_trace_socket(int linux_domain, uint64_t linux_type,
                             int protocol, int64_t result) {
    if (g_socket_trace_count >= M3_SOCKET_TRACE_LIMIT) return;
    ++g_socket_trace_count;
    char buffer[224];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "hrt-m3: Linux socket bridge domain=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)linux_domain);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " type=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), linux_type);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " protocol=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)protocol);
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

static int host_socket_domain(int linux_domain) {
    switch (linux_domain) {
        case LINUX_AF_UNSPEC: return AF_UNSPEC;
        case LINUX_AF_UNIX: return AF_UNIX;
        case LINUX_AF_INET: return AF_INET;
        case LINUX_AF_INET6: return AF_INET6;
        default: return -1;
    }
}

static int host_socket_type(uint64_t linux_type) {
    switch (linux_type & LINUX_SOCK_TYPE_MASK) {
        case 1u: return SOCK_STREAM;
        case 2u: return SOCK_DGRAM;
        case 3u: return SOCK_RAW;
#ifdef SOCK_RDM
        case 4u: return SOCK_RDM;
#endif
#ifdef SOCK_SEQPACKET
        case 5u: return SOCK_SEQPACKET;
#endif
        default: return -1;
    }
}

static int apply_socket_descriptor_flags(int fd, uint64_t linux_type) {
    if ((linux_type & LINUX_SOCK_CLOEXEC) != 0u) {
        if (fcntl(fd, F_SETFD, FD_CLOEXEC) != 0) return -1;
    }
    if ((linux_type & LINUX_SOCK_NONBLOCK) != 0u) {
        int current = fcntl(fd, F_GETFL, 0);
        if (current < 0) return -1;
        if (fcntl(fd, F_SETFL, current | O_NONBLOCK) != 0) return -1;
    }
    return 0;
}

static int64_t host_socket_bridge(int linux_domain, uint64_t linux_type,
                                  int protocol) {
    const uint64_t supported_flags =
        LINUX_SOCK_TYPE_MASK | LINUX_SOCK_NONBLOCK | LINUX_SOCK_CLOEXEC;
    if ((linux_type & ~supported_flags) != 0u) {
        raw_trace_socket(linux_domain, linux_type, protocol,
                         -LINUX_EINVAL);
        return -LINUX_EINVAL;
    }

    int domain = host_socket_domain(linux_domain);
    if (domain < 0) {
        raw_trace_socket(linux_domain, linux_type, protocol,
                         -LINUX_EAFNOSUPPORT);
        return -LINUX_EAFNOSUPPORT;
    }
    int type = host_socket_type(linux_type);
    if (type < 0) {
        raw_trace_socket(linux_domain, linux_type, protocol,
                         -LINUX_ESOCKTNOSUPPORT);
        return -LINUX_ESOCKTNOSUPPORT;
    }

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int fd = socket(domain, type, protocol);
    int saved_errno = errno;
    if (fd >= 0 && apply_socket_descriptor_flags(fd, linux_type) != 0) {
        saved_errno = errno;
        (void)close(fd);
        fd = -1;
    }
    restore_guest_context(guest);

    int64_t result = linux_host_result((int64_t)fd, saved_errno);
    raw_trace_socket(linux_domain, linux_type, protocol, result);
    return result;
}

static int64_t host_mkdir_bridge(const char *guest_path, uint64_t mode) {
    if (guest_path == NULL) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    char path[PATH_MAX];
    if (translate_guest_path(guest_path, path, sizeof(path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    errno = 0;
    int host_result = mkdir(path, (mode_t)(mode & UINT64_C(07777)));
    int saved_errno = errno;
    restore_guest_context(guest);
    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    raw_trace_posix_path("mkdir", path, result);
    return result;
}

static int64_t host_unlink_bridge(const char *guest_path) {
    if (guest_path == NULL) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    char path[PATH_MAX];
    if (translate_guest_path(guest_path, path, sizeof(path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    errno = 0;
    int host_result = unlink(path);
    int saved_errno = errno;
    restore_guest_context(guest);
    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    raw_trace_posix_path("unlink", path, result);
    return result;
}

static int64_t bridge_time(int64_t *guest_time) {
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    time_t host_result = time(NULL);
    int saved_errno = errno;
    restore_guest_context(guest);
    if (host_result == (time_t)-1) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }
    int64_t result = (int64_t)host_result;
    if (guest_time != NULL) *guest_time = result;
    return result;
}

'''
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        bridge + "static int64_t host_close_bridge(int fd) {\n",
        "basic POSIX bridges",
    )

    dispatch_anchor = '''        case LINUX_SYS_ACCESS:
            result = host_access_bridge(
                LINUX_AT_FDCWD, (const char *)(uintptr_t)state->__rdi,
                (int)state->__rsi, 0u);
            break;
        case LINUX_SYS_MADVISE:
'''
    dispatch_replacement = '''        case LINUX_SYS_ACCESS:
            result = host_access_bridge(
                LINUX_AT_FDCWD, (const char *)(uintptr_t)state->__rdi,
                (int)state->__rsi, 0u);
            break;
        case LINUX_SYS_SOCKET:
            result = host_socket_bridge((int)state->__rdi, state->__rsi,
                                        (int)state->__rdx);
            break;
        case LINUX_SYS_MKDIR:
            result = host_mkdir_bridge(
                (const char *)(uintptr_t)state->__rdi, state->__rsi);
            break;
        case LINUX_SYS_UNLINK:
            result = host_unlink_bridge(
                (const char *)(uintptr_t)state->__rdi);
            break;
        case LINUX_SYS_TIME:
            result = bridge_time((int64_t *)(uintptr_t)state->__rdi);
            break;
        case LINUX_SYS_MADVISE:
'''
    text = replace_once(text, dispatch_anchor, dispatch_replacement,
                        "basic POSIX dispatch")

    for marker in (
        "case LINUX_SYS_SOCKET:",
        "case LINUX_SYS_MKDIR:",
        "case LINUX_SYS_UNLINK:",
        "case LINUX_SYS_TIME:",
        "Linux socket bridge domain=",
        'raw_trace_posix_path("mkdir"',
        'raw_trace_posix_path("unlink"',
    ):
        if text.count(marker) != 1:
            raise SystemExit(f"injected marker count mismatch: {marker!r}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
