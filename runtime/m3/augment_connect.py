#!/usr/bin/env python3
"""Translate Linux x86-64 connect(2) calls used during HWord startup.

The exact application opens nonblocking AF_UNIX sockets after its official
QPA is loaded.  Linux and Darwin sockaddr_un layouts differ, and absolute
Linux socket paths must remain inside the verified guest root.  This transform
copies and roots pathname sockets, rejects abstract-namespace sockets rather
than silently misrouting them, and records the translated path and Linux
result.  Every source edit is anchored exactly once.
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
        "#include <sys/socket.h>\n",
        "#include <sys/socket.h>\n#include <sys/un.h>\n",
        "UNIX socket header",
    )

    text = replace_once(
        text,
        "#ifndef LINUX_SYS_SOCKET\n"
        "#define LINUX_SYS_SOCKET UINT64_C(41)\n"
        "#endif\n",
        "#ifndef LINUX_SYS_SOCKET\n"
        "#define LINUX_SYS_SOCKET UINT64_C(41)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_CONNECT\n"
        "#define LINUX_SYS_CONNECT UINT64_C(42)\n"
        "#endif\n",
        "connect syscall constant",
    )

    text = replace_once(
        text,
        "#ifndef LINUX_EAFNOSUPPORT\n"
        "#define LINUX_EAFNOSUPPORT 97\n"
        "#endif\n",
        "#ifndef LINUX_EAFNOSUPPORT\n"
        "#define LINUX_EAFNOSUPPORT 97\n"
        "#endif\n"
        "#ifndef LINUX_ENOTSOCK\n"
        "#define LINUX_ENOTSOCK 88\n"
        "#endif\n"
        "#ifndef LINUX_EADDRINUSE\n"
        "#define LINUX_EADDRINUSE 98\n"
        "#endif\n"
        "#ifndef LINUX_EADDRNOTAVAIL\n"
        "#define LINUX_EADDRNOTAVAIL 99\n"
        "#endif\n"
        "#ifndef LINUX_ENETUNREACH\n"
        "#define LINUX_ENETUNREACH 101\n"
        "#endif\n"
        "#ifndef LINUX_ECONNRESET\n"
        "#define LINUX_ECONNRESET 104\n"
        "#endif\n"
        "#ifndef LINUX_EISCONN\n"
        "#define LINUX_EISCONN 106\n"
        "#endif\n"
        "#ifndef LINUX_ENOTCONN\n"
        "#define LINUX_ENOTCONN 107\n"
        "#endif\n"
        "#ifndef LINUX_ETIMEDOUT\n"
        "#define LINUX_ETIMEDOUT 110\n"
        "#endif\n"
        "#ifndef LINUX_ECONNREFUSED\n"
        "#define LINUX_ECONNREFUSED 111\n"
        "#endif\n"
        "#ifndef LINUX_EALREADY\n"
        "#define LINUX_EALREADY 114\n"
        "#endif\n"
        "#ifndef LINUX_EINPROGRESS\n"
        "#define LINUX_EINPROGRESS 115\n"
        "#endif\n",
        "connect errno constants",
    )

    text = replace_once(
        text,
        "#ifdef EAFNOSUPPORT\n"
        "        case EAFNOSUPPORT: return LINUX_EAFNOSUPPORT;\n"
        "#endif\n"
        "        default: return LINUX_EIO;\n",
        "#ifdef EAFNOSUPPORT\n"
        "        case EAFNOSUPPORT: return LINUX_EAFNOSUPPORT;\n"
        "#endif\n"
        "#ifdef ENOTSOCK\n"
        "        case ENOTSOCK: return LINUX_ENOTSOCK;\n"
        "#endif\n"
        "#ifdef EADDRINUSE\n"
        "        case EADDRINUSE: return LINUX_EADDRINUSE;\n"
        "#endif\n"
        "#ifdef EADDRNOTAVAIL\n"
        "        case EADDRNOTAVAIL: return LINUX_EADDRNOTAVAIL;\n"
        "#endif\n"
        "#ifdef ENETUNREACH\n"
        "        case ENETUNREACH: return LINUX_ENETUNREACH;\n"
        "#endif\n"
        "#ifdef ECONNRESET\n"
        "        case ECONNRESET: return LINUX_ECONNRESET;\n"
        "#endif\n"
        "#ifdef EISCONN\n"
        "        case EISCONN: return LINUX_EISCONN;\n"
        "#endif\n"
        "#ifdef ENOTCONN\n"
        "        case ENOTCONN: return LINUX_ENOTCONN;\n"
        "#endif\n"
        "#ifdef ETIMEDOUT\n"
        "        case ETIMEDOUT: return LINUX_ETIMEDOUT;\n"
        "#endif\n"
        "#ifdef ECONNREFUSED\n"
        "        case ECONNREFUSED: return LINUX_ECONNREFUSED;\n"
        "#endif\n"
        "#ifdef EALREADY\n"
        "        case EALREADY: return LINUX_EALREADY;\n"
        "#endif\n"
        "#ifdef EINPROGRESS\n"
        "        case EINPROGRESS: return LINUX_EINPROGRESS;\n"
        "#endif\n"
        "        default: return LINUX_EIO;\n",
        "connect errno translation",
    )

    bridge = r'''
#define M3_LINUX_SUN_PATH_SIZE 108u
#define M3_CONNECT_TRACE_LIMIT 16u

static unsigned int g_connect_trace_count;

static void raw_trace_connect(int fd, uint16_t family,
                              const char *guest_path,
                              const char *host_path,
                              int64_t result) {
    if (g_connect_trace_count >= M3_CONNECT_TRACE_LIMIT) return;
    ++g_connect_trace_count;
    char buffer[640];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "hrt-m3: Linux connect bridge fd=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)fd);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " family=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), family);
    if (guest_path != NULL) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " guest-path=");
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      guest_path);
    }
    if (host_path != NULL) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " host-path=");
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      host_path);
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

static int64_t host_connect_bridge(int fd, const void *guest_address,
                                   size_t guest_length) {
    if (guest_address == NULL) return -LINUX_EFAULT;
    if (guest_length < sizeof(uint16_t)) return -LINUX_EINVAL;

    uint16_t linux_family;
    memcpy(&linux_family, guest_address, sizeof(linux_family));
    if (linux_family != LINUX_AF_UNIX) {
        raw_trace_connect(fd, linux_family, NULL, NULL,
                          -LINUX_EAFNOSUPPORT);
        return -LINUX_EAFNOSUPPORT;
    }

    if (guest_length <= sizeof(uint16_t)) return -LINUX_EINVAL;
    size_t available = guest_length - sizeof(uint16_t);
    if (available > M3_LINUX_SUN_PATH_SIZE) {
        available = M3_LINUX_SUN_PATH_SIZE;
    }
    const char *linux_path =
        (const char *)guest_address + sizeof(uint16_t);
    if (linux_path[0] == '\0') {
        static const char abstract_path[] = "<abstract>";
        raw_trace_connect(fd, linux_family, abstract_path, NULL,
                          -LINUX_EAFNOSUPPORT);
        return -LINUX_EAFNOSUPPORT;
    }

    size_t guest_path_length = strnlen(linux_path, available);
    if (guest_path_length == 0u) return -LINUX_EINVAL;
    if (guest_path_length >= M3_LINUX_SUN_PATH_SIZE) {
        return -LINUX_ENAMETOOLONG;
    }
    char guest_path[M3_LINUX_SUN_PATH_SIZE + 1u];
    memcpy(guest_path, linux_path, guest_path_length);
    guest_path[guest_path_length] = '\0';

    uintptr_t guest = switch_to_host_context();
    char translated[PATH_MAX];
    if (translate_guest_path(guest_path, translated,
                             sizeof(translated)) != 0) {
        restore_guest_context(guest);
        raw_trace_connect(fd, linux_family, guest_path, NULL,
                          -LINUX_ENAMETOOLONG);
        return -LINUX_ENAMETOOLONG;
    }

    struct sockaddr_un host_address;
    memset(&host_address, 0, sizeof(host_address));
    size_t host_path_length = strlen(translated);
    if (host_path_length >= sizeof(host_address.sun_path)) {
        restore_guest_context(guest);
        raw_trace_connect(fd, linux_family, guest_path, translated,
                          -LINUX_ENAMETOOLONG);
        return -LINUX_ENAMETOOLONG;
    }
    host_address.sun_family = AF_UNIX;
    memcpy(host_address.sun_path, translated, host_path_length + 1u);
    size_t host_length = offsetof(struct sockaddr_un, sun_path) +
                         host_path_length + 1u;
    if (host_length > UINT8_MAX) {
        restore_guest_context(guest);
        raw_trace_connect(fd, linux_family, guest_path, translated,
                          -LINUX_ENAMETOOLONG);
        return -LINUX_ENAMETOOLONG;
    }
    host_address.sun_len = (uint8_t)host_length;

    errno = 0;
    int host_result = connect(fd, (const struct sockaddr *)&host_address,
                              (socklen_t)host_length);
    int saved_errno = errno;
    restore_guest_context(guest);

    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    raw_trace_connect(fd, linux_family, guest_path, translated, result);
    return result;
}

'''
    text = replace_once(
        text,
        "static int64_t host_socket_bridge(int linux_domain, "
        "uint64_t linux_type,\n",
        bridge + "static int64_t host_socket_bridge(int linux_domain, "
        "uint64_t linux_type,\n",
        "connect bridge",
    )

    text = replace_once(
        text,
        "        case LINUX_SYS_SOCKET:\n"
        "            result = host_socket_bridge((int)state->__rdi, "
        "state->__rsi,\n"
        "                                        (int)state->__rdx);\n"
        "            break;\n"
        "        case LINUX_SYS_MKDIR:\n",
        "        case LINUX_SYS_SOCKET:\n"
        "            result = host_socket_bridge((int)state->__rdi, "
        "state->__rsi,\n"
        "                                        (int)state->__rdx);\n"
        "            break;\n"
        "        case LINUX_SYS_CONNECT:\n"
        "            result = host_connect_bridge(\n"
        "                (int)state->__rdi,\n"
        "                (const void *)(uintptr_t)state->__rsi,\n"
        "                (size_t)state->__rdx);\n"
        "            break;\n"
        "        case LINUX_SYS_MKDIR:\n",
        "connect dispatch",
    )

    if text.count("case LINUX_SYS_CONNECT:") != 1:
        raise SystemExit("connect dispatch was not injected exactly once")
    if text.count("host_connect_bridge(") != 2:
        raise SystemExit("connect bridge definition/call count mismatch")
    if text.count("Linux connect bridge fd=") != 1:
        raise SystemExit("connect trace marker count mismatch")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
