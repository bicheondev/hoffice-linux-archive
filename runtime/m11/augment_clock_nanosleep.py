#!/usr/bin/env python3
"""Add the Linux x86-64 ``clock_nanosleep`` boundary to the host bridge.

The exact HWord document-settle replay reaches a stable ``DocumentTabImpl`` but
its Qt and worker threads repeatedly issue syscall 230.  Returning ``ENOSYS``
turns every requested sleep into a busy loop and can prevent the asynchronous
editor frame from reaching its normal scheduling frontier.

This transform implements the Linux ABI without changing any guest binary:

* syscall 230 and ``TIMER_ABSTIME`` are defined explicitly;
* common Linux clock IDs are translated to their Darwin counterparts;
* relative requests use host ``nanosleep`` and report a remaining interval on
  interruption;
* absolute requests repeatedly compare the selected host clock against the
  Linux deadline and sleep only for the positive delta; and
* all libc calls execute after restoring the Darwin pthread/TSD GS base.

Unsupported flags or clock IDs fail closed with ``EINVAL``.  Every edit uses an
exact source anchor and a bounded trace records the observed timing route.
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
    if "HRT M11 SLEEP:" in text:
        raise SystemExit("M11 clock_nanosleep compatibility is already present")

    syscall_anchor = (
        "#ifndef LINUX_SYS_SOCKET\n"
        "#define LINUX_SYS_SOCKET UINT64_C(41)\n"
        "#endif\n"
    )
    syscall_replacement = syscall_anchor + (
        "#ifndef LINUX_SYS_CLOCK_NANOSLEEP\n"
        "#define LINUX_SYS_CLOCK_NANOSLEEP UINT64_C(230)\n"
        "#endif\n"
        "#define M11_LINUX_TIMER_ABSTIME UINT64_C(1)\n"
    )
    text = replace_once(text, syscall_anchor, syscall_replacement,
                        "clock_nanosleep constants")

    helper_anchor = '''static int64_t bridge_gettimeofday(LinuxTimeval *guest_time) {
'''
    helper = r'''#define M11_SLEEP_TRACE_LIMIT 32u

static unsigned int g_m11_sleep_trace_count;

static void m11_trace_clock_nanosleep(int linux_clock_id, uint64_t flags,
                                      const LinuxTimespec *request,
                                      int64_t result) {
    if (g_m11_sleep_trace_count >= M11_SLEEP_TRACE_LIMIT)
        return;
    ++g_m11_sleep_trace_count;
    char buffer[320];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M11 SLEEP: clock=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)linux_clock_id);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " flags=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), flags);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " sec=");
    if (request != NULL && request->tv_sec < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(
            buffer, cursor, sizeof(buffer),
            (uint64_t)(-(request->tv_sec + 1)) + UINT64_C(1));
    } else {
        cursor = trace_append_decimal(
            buffer, cursor, sizeof(buffer),
            request != NULL ? (uint64_t)request->tv_sec : 0u);
    }
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " nsec=");
    cursor = trace_append_decimal(
        buffer, cursor, sizeof(buffer),
        request != NULL ? (uint64_t)request->tv_nsec : 0u);
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

static int m11_host_clock_id(int linux_clock_id, clockid_t *host_clock_id) {
    if (host_clock_id == NULL) return -1;
    switch (linux_clock_id) {
        case 0: /* CLOCK_REALTIME */
            *host_clock_id = CLOCK_REALTIME;
            return 0;
        case 1: /* CLOCK_MONOTONIC */
            *host_clock_id = CLOCK_MONOTONIC;
            return 0;
#ifdef CLOCK_PROCESS_CPUTIME_ID
        case 2:
            *host_clock_id = CLOCK_PROCESS_CPUTIME_ID;
            return 0;
#endif
#ifdef CLOCK_THREAD_CPUTIME_ID
        case 3:
            *host_clock_id = CLOCK_THREAD_CPUTIME_ID;
            return 0;
#endif
#ifdef CLOCK_MONOTONIC_RAW
        case 4:
            *host_clock_id = CLOCK_MONOTONIC_RAW;
            return 0;
#endif
        case 5: /* CLOCK_REALTIME_COARSE */
        case 8: /* CLOCK_REALTIME_ALARM */
            *host_clock_id = CLOCK_REALTIME;
            return 0;
        case 6: /* CLOCK_MONOTONIC_COARSE */
        case 7: /* CLOCK_BOOTTIME */
        case 9: /* CLOCK_BOOTTIME_ALARM */
            *host_clock_id = CLOCK_MONOTONIC;
            return 0;
        default:
            return -1;
    }
}

static int m11_valid_linux_timespec(const LinuxTimespec *value) {
    return value != NULL && value->tv_sec >= 0 &&
        value->tv_nsec >= 0 && value->tv_nsec < INT64_C(1000000000);
}

static int m11_timespec_at_or_after(const struct timespec *left,
                                    const struct timespec *right) {
    return left->tv_sec > right->tv_sec ||
        (left->tv_sec == right->tv_sec && left->tv_nsec >= right->tv_nsec);
}

static struct timespec m11_timespec_delta(const struct timespec *deadline,
                                          const struct timespec *now) {
    struct timespec delta;
    delta.tv_sec = deadline->tv_sec - now->tv_sec;
    delta.tv_nsec = deadline->tv_nsec - now->tv_nsec;
    if (delta.tv_nsec < 0) {
        --delta.tv_sec;
        delta.tv_nsec += 1000000000L;
    }
    if (delta.tv_sec < 0) {
        delta.tv_sec = 0;
        delta.tv_nsec = 0;
    }
    return delta;
}

static int64_t bridge_clock_nanosleep(
    int linux_clock_id, uint64_t flags,
    const LinuxTimespec *guest_request, LinuxTimespec *guest_remaining) {
    if (guest_request == NULL) return -LINUX_EFAULT;
    const LinuxTimespec request = *guest_request;
    if (!m11_valid_linux_timespec(&request)) {
        m11_trace_clock_nanosleep(linux_clock_id, flags, &request,
                                  -LINUX_EINVAL);
        return -LINUX_EINVAL;
    }
    if ((flags & ~M11_LINUX_TIMER_ABSTIME) != 0u) {
        m11_trace_clock_nanosleep(linux_clock_id, flags, &request,
                                  -LINUX_EINVAL);
        return -LINUX_EINVAL;
    }

    clockid_t host_clock_id;
    if (m11_host_clock_id(linux_clock_id, &host_clock_id) != 0) {
        m11_trace_clock_nanosleep(linux_clock_id, flags, &request,
                                  -LINUX_EINVAL);
        return -LINUX_EINVAL;
    }

    const struct timespec requested = {
        .tv_sec = (time_t)request.tv_sec,
        .tv_nsec = (long)request.tv_nsec,
    };
    uintptr_t guest = switch_to_host_context();
    int host_result = 0;
    int saved_errno = 0;
    struct timespec host_remaining;
    memset(&host_remaining, 0, sizeof(host_remaining));

    if ((flags & M11_LINUX_TIMER_ABSTIME) == 0u) {
        errno = 0;
        host_result = nanosleep(&requested, &host_remaining);
        saved_errno = errno;
    } else {
        for (;;) {
            struct timespec now;
            errno = 0;
            host_result = clock_gettime(host_clock_id, &now);
            saved_errno = errno;
            if (host_result != 0 || m11_timespec_at_or_after(&now, &requested))
                break;
            const struct timespec delta = m11_timespec_delta(&requested, &now);
            errno = 0;
            host_result = nanosleep(&delta, NULL);
            saved_errno = errno;
            if (host_result != 0)
                break;
        }
    }

    restore_guest_context(guest);
    if (host_result == 0) {
        m11_trace_clock_nanosleep(linux_clock_id, flags, &request, 0);
        return 0;
    }

    if ((flags & M11_LINUX_TIMER_ABSTIME) == 0u &&
        saved_errno == EINTR && guest_remaining != NULL) {
        guest_remaining->tv_sec = (int64_t)host_remaining.tv_sec;
        guest_remaining->tv_nsec = (int64_t)host_remaining.tv_nsec;
    }
    const int64_t result = -(int64_t)linux_errno_from_host(saved_errno);
    m11_trace_clock_nanosleep(linux_clock_id, flags, &request, result);
    return result;
}

static int64_t bridge_gettimeofday(LinuxTimeval *guest_time) {
'''
    text = replace_once(text, helper_anchor, helper,
                        "clock_nanosleep bridge insertion")

    dispatch_anchor = '''        case LINUX_SYS_CLOCK_GETTIME:
            result = bridge_clock_gettime(
                (int)state->__rdi,
                (LinuxTimespec *)(uintptr_t)state->__rsi);
            break;
        case LINUX_SYS_OPENAT:
'''
    dispatch_replacement = '''        case LINUX_SYS_CLOCK_GETTIME:
            result = bridge_clock_gettime(
                (int)state->__rdi,
                (LinuxTimespec *)(uintptr_t)state->__rsi);
            break;
        case LINUX_SYS_CLOCK_NANOSLEEP:
            result = bridge_clock_nanosleep(
                (int)state->__rdi, state->__rsi,
                (const LinuxTimespec *)(uintptr_t)state->__rdx,
                (LinuxTimespec *)(uintptr_t)state->__r10);
            break;
        case LINUX_SYS_OPENAT:
'''
    text = replace_once(text, dispatch_anchor, dispatch_replacement,
                        "clock_nanosleep dispatch")

    required = {
        "HRT M11 SLEEP:": 1,
        "LINUX_SYS_CLOCK_NANOSLEEP": 3,
        "M11_LINUX_TIMER_ABSTIME": 4,
        "bridge_clock_nanosleep(": 2,
        "m11_host_clock_id(": 2,
        "nanosleep(&requested": 1,
        "nanosleep(&delta": 1,
        "case LINUX_SYS_CLOCK_NANOSLEEP:": 1,
        "guest_remaining->tv_sec": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"clock_nanosleep marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
