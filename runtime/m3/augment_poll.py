#!/usr/bin/env python3
"""Inject Linux x86-64 poll(2) translation into a generated M3 bridge.

Linux and Darwin use the same 8-byte pollfd layout, but their writable-band
bits differ.  This transform therefore copies through a bounded host array,
translates request and result flags explicitly, switches back to the host TLS
context around libc poll(), and records the first long wait as a durable event
loop boundary.
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

    # Preserve a preceding mature poll/ppoll + epoll + tgkill
    # translation rather than injecting the older poll-only
    # variant a second time.
    if (
        "case LINUX_SYS_PPOLL:" in text
        and "host_poll_bridge(" in text
    ):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        return

    text = replace_once(
        text,
        "#include <limits.h>\n",
        "#include <limits.h>\n#include <poll.h>\n",
        "poll header",
    )

    text = replace_once(
        text,
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n",
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n"
        "#ifndef LINUX_SYS_POLL\n"
        "#define LINUX_SYS_POLL UINT64_C(7)\n"
        "#endif\n",
        "Linux poll syscall constant",
    )

    bridge = r'''
#define LINUX_POLLIN      UINT16_C(0x0001)
#define LINUX_POLLPRI     UINT16_C(0x0002)
#define LINUX_POLLOUT     UINT16_C(0x0004)
#define LINUX_POLLERR     UINT16_C(0x0008)
#define LINUX_POLLHUP     UINT16_C(0x0010)
#define LINUX_POLLNVAL    UINT16_C(0x0020)
#define LINUX_POLLRDNORM  UINT16_C(0x0040)
#define LINUX_POLLRDBAND  UINT16_C(0x0080)
#define LINUX_POLLWRNORM  UINT16_C(0x0100)
#define LINUX_POLLWRBAND  UINT16_C(0x0200)
#define LINUX_POLLRDHUP   UINT16_C(0x2000)
#define M3_MAX_POLL_FDS   1024u

/* Linux x86-64 and Darwin both expose int/short/short pollfd records. */
typedef struct {
    int fd;
    int16_t events;
    int16_t revents;
} LinuxPollfd;

_Static_assert(sizeof(LinuxPollfd) == sizeof(struct pollfd),
               "Linux and Darwin pollfd size");
_Static_assert(_Alignof(LinuxPollfd) == _Alignof(struct pollfd),
               "Linux and Darwin pollfd alignment");

static struct pollfd g_host_pollfds[M3_MAX_POLL_FDS];
static volatile sig_atomic_t g_poll_long_enter_logged;
static volatile sig_atomic_t g_poll_long_return_logged;

static short linux_poll_events_to_host(int16_t linux_events) {
    const uint16_t events = (uint16_t)linux_events;
    short host = 0;
    if ((events & LINUX_POLLIN) != 0u) host |= POLLIN;
    if ((events & LINUX_POLLPRI) != 0u) host |= POLLPRI;
    if ((events & LINUX_POLLOUT) != 0u) host |= POLLOUT;
    if ((events & LINUX_POLLRDNORM) != 0u) host |= POLLRDNORM;
    if ((events & LINUX_POLLRDBAND) != 0u) host |= POLLRDBAND;
    if ((events & LINUX_POLLWRNORM) != 0u) host |= POLLOUT;
    if ((events & LINUX_POLLWRBAND) != 0u) host |= POLLWRBAND;
    /* Darwin has no POLLRDHUP request bit. Readability plus HUP is closest. */
    if ((events & LINUX_POLLRDHUP) != 0u) host |= POLLIN;
    return host;
}

static int16_t host_poll_events_to_linux(short host_events,
                                         int16_t linux_requested) {
    const uint16_t requested = (uint16_t)linux_requested;
    uint16_t linux_events = 0u;
    if ((host_events & POLLIN) != 0) linux_events |= LINUX_POLLIN;
    if ((host_events & POLLPRI) != 0) linux_events |= LINUX_POLLPRI;
    if ((host_events & POLLOUT) != 0) {
        linux_events |= LINUX_POLLOUT;
        if ((requested & LINUX_POLLWRNORM) != 0u) {
            linux_events |= LINUX_POLLWRNORM;
        }
    }
    if ((host_events & POLLRDNORM) != 0) linux_events |= LINUX_POLLRDNORM;
    if ((host_events & POLLRDBAND) != 0) linux_events |= LINUX_POLLRDBAND;
    if ((host_events & POLLWRBAND) != 0 &&
        (requested & LINUX_POLLWRBAND) != 0u) {
        linux_events |= LINUX_POLLWRBAND;
    }
    if ((host_events & POLLERR) != 0) linux_events |= LINUX_POLLERR;
    if ((host_events & POLLHUP) != 0) {
        linux_events |= LINUX_POLLHUP;
        if ((requested & LINUX_POLLRDHUP) != 0u) {
            linux_events |= LINUX_POLLRDHUP;
        }
    }
    if ((host_events & POLLNVAL) != 0) linux_events |= LINUX_POLLNVAL;
    return (int16_t)linux_events;
}

static void raw_trace_poll_boundary(const char *stage, size_t count,
                                    int timeout, int64_t result) {
    char buffer[192];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "hrt-m3: Linux poll bridge ");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), stage);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " nfds=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), count);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " timeout=");
    if (timeout < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-(int64_t)timeout));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)timeout);
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

static int64_t host_poll_bridge(LinuxPollfd *guest_fds, size_t count,
                                int timeout) {
    if (count > M3_MAX_POLL_FDS) return -LINUX_EINVAL;
    if (count != 0u && guest_fds == NULL) return -LINUX_EFAULT;

    for (size_t index = 0u; index < count; ++index) {
        g_host_pollfds[index].fd = guest_fds[index].fd;
        g_host_pollfds[index].events =
            linux_poll_events_to_host(guest_fds[index].events);
        g_host_pollfds[index].revents = 0;
        guest_fds[index].revents = 0;
    }

    const int long_wait = timeout < 0 || timeout >= 1000;
    if (long_wait && !g_poll_long_enter_logged) {
        g_poll_long_enter_logged = 1;
        raw_trace_poll_boundary("long-enter", count, timeout, 0);
    }

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result = poll(g_host_pollfds, (nfds_t)count, timeout);
    int saved_errno = errno;

    if (result >= 0) {
        for (size_t index = 0u; index < count; ++index) {
            guest_fds[index].revents = host_poll_events_to_linux(
                g_host_pollfds[index].revents, guest_fds[index].events);
        }
    }
    restore_guest_context(guest);

    int64_t linux_result = linux_host_result((int64_t)result, saved_errno);
    if (long_wait && !g_poll_long_return_logged) {
        g_poll_long_return_logged = 1;
        raw_trace_poll_boundary("long-return", count, timeout, linux_result);
    }
    return linux_result;
}

'''
    text = replace_once(
        text,
        "static int64_t host_read_bridge(int fd, void *buffer, size_t size) {\n",
        bridge + "static int64_t host_read_bridge(int fd, void *buffer, size_t size) {\n",
        "poll bridge",
    )

    text = replace_once(
        text,
        "    switch (state->__rax) {\n"
        "        case LINUX_SYS_READ:\n",
        "    switch (state->__rax) {\n"
        "        case LINUX_SYS_POLL:\n"
        "            result = host_poll_bridge(\n"
        "                (LinuxPollfd *)(uintptr_t)state->__rdi,\n"
        "                (size_t)state->__rsi, (int)(int32_t)state->__rdx);\n"
        "            break;\n"
        "        case LINUX_SYS_READ:\n",
        "poll dispatch",
    )

    if text.count("case LINUX_SYS_POLL:") != 1:
        raise SystemExit("poll dispatch was not injected exactly once")
    if text.count("host_poll_bridge(") != 2:
        raise SystemExit("poll bridge definition/call count mismatch")
    if 'raw_trace_poll_boundary("long-enter"' not in text:
        raise SystemExit("durable long-wait marker was not retained")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
