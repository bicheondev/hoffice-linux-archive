#!/usr/bin/env python3
"""Inject bounded path diagnostics into the mature macOS syscall bridge.

The HWord bootstrap currently reaches a rendered ``Initialization Error``
dialog.  Static analysis ties that branch to the HncBaseDraw font database
(``FontMap.dat`` and ``fontinfo.dat``).  This generator records all failed path
operations plus successful operations whose paths mention the font database.

The trace executes while the bridge has restored the host GS base and emits
only through the existing raw Darwin ``write`` syscall.  No stdio, allocation,
or Objective-C operation occurs from the SIGILL path.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def inject_once_in_function(
    text: str,
    function_start: str,
    next_function_start: str,
    needle: str,
    replacement: str,
    label: str,
) -> str:
    """Replace one anchor inside one named C function only.

    The mature filesystem/eventfd composition may insert unrelated helper code
    elsewhere in the translation unit.  Limiting the search to the readlink
    function keeps the transform fail-closed without depending on the exact
    text immediately preceding the next function.
    """
    start_count = text.count(function_start)
    if start_count != 1:
        raise SystemExit(
            f"{label}: expected one function start, found {start_count}")
    start = text.index(function_start)
    end = text.find(next_function_start, start + len(function_start))
    if end < 0:
        raise SystemExit(f"{label}: next function anchor not found")

    function_text = text[start:end]
    needle_count = function_text.count(needle)
    if needle_count != 1:
        excerpt = function_text[-1800:].replace("\n", "\\n")
        raise SystemExit(
            f"{label}: expected exactly one in-function anchor, "
            f"found {needle_count}; function-tail={excerpt}")
    function_text = function_text.replace(needle, replacement, 1)
    return text[:start] + function_text + text[end:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M9 PATH:" in text:
        raise SystemExit("M9 path tracing is already present")

    helper_anchor = '''static void raw_write_literal(const char *message, size_t length) {
    (void)raw_bsd_syscall3(DARWIN_SYS_WRITE, STDERR_FILENO,
                           (uint64_t)(uintptr_t)message, length);
}
'''
    helper = helper_anchor + r'''
#define M9_PATH_TRACE_LIMIT 2048u
#define M9_PATH_TRACE_BUFFER 1536u

static unsigned int g_m9_path_trace_count;

static size_t m9_append_char(char *buffer, size_t cursor,
                             size_t capacity, char value) {
    if (cursor < capacity) buffer[cursor] = value;
    return cursor + 1u;
}

static size_t m9_append_literal(char *buffer, size_t cursor,
                                size_t capacity, const char *value) {
    if (value == NULL) value = "(null)";
    for (size_t index = 0u; value[index] != '\0'; ++index) {
        cursor = m9_append_char(buffer, cursor, capacity, value[index]);
    }
    return cursor;
}

static size_t m9_append_unsigned(char *buffer, size_t cursor,
                                 size_t capacity, uint64_t value) {
    char digits[24];
    size_t count = 0u;
    do {
        digits[count++] = (char)('0' + value % 10u);
        value /= 10u;
    } while (value != 0u && count < sizeof(digits));
    while (count != 0u) {
        cursor = m9_append_char(buffer, cursor, capacity,
                                digits[--count]);
    }
    return cursor;
}

static size_t m9_append_signed(char *buffer, size_t cursor,
                               size_t capacity, int64_t value) {
    uint64_t magnitude;
    if (value < 0) {
        cursor = m9_append_char(buffer, cursor, capacity, '-');
        magnitude = (uint64_t)(-(value + 1)) + 1u;
    } else {
        magnitude = (uint64_t)value;
    }
    return m9_append_unsigned(buffer, cursor, capacity, magnitude);
}

static unsigned char m9_ascii_lower(unsigned char value) {
    if (value >= (unsigned char)'A' && value <= (unsigned char)'Z') {
        return (unsigned char)(value - (unsigned char)'A' +
                               (unsigned char)'a');
    }
    return value;
}

static int m9_contains_case_insensitive(const char *value,
                                        const char *needle) {
    if (value == NULL || needle == NULL || needle[0] == '\0') return 0;
    for (size_t start = 0u; value[start] != '\0'; ++start) {
        size_t offset = 0u;
        while (needle[offset] != '\0' && value[start + offset] != '\0' &&
               m9_ascii_lower((unsigned char)value[start + offset]) ==
               m9_ascii_lower((unsigned char)needle[offset])) {
            ++offset;
        }
        if (needle[offset] == '\0') return 1;
    }
    return 0;
}

static int m9_interesting_path(const char *guest_path,
                               const char *host_path,
                               int64_t host_result) {
    if (host_result < 0) return 1;
    static const char *const needles[] = {
        "fontmap.dat",
        "fontinfo.dat",
        "fontdb",
        "shared/fonts",
        "optioninfo",
        "fontconfig",
    };
    for (size_t index = 0u;
         index < sizeof(needles) / sizeof(needles[0]); ++index) {
        if (m9_contains_case_insensitive(guest_path, needles[index]) ||
            m9_contains_case_insensitive(host_path, needles[index])) {
            return 1;
        }
    }
    return 0;
}

static void m9_trace_path(const char *operation,
                          const char *guest_path,
                          const char *host_path,
                          int64_t host_result,
                          int host_errno) {
    if (g_m9_path_trace_count >= M9_PATH_TRACE_LIMIT) return;
    if (!m9_interesting_path(guest_path, host_path, host_result)) return;
    ++g_m9_path_trace_count;

    char buffer[M9_PATH_TRACE_BUFFER];
    size_t cursor = 0u;
    cursor = m9_append_literal(buffer, cursor, sizeof(buffer),
                               "HRT M9 PATH: op=");
    cursor = m9_append_literal(buffer, cursor, sizeof(buffer), operation);
    cursor = m9_append_literal(buffer, cursor, sizeof(buffer), " result=");
    cursor = m9_append_signed(buffer, cursor, sizeof(buffer), host_result);
    cursor = m9_append_literal(buffer, cursor, sizeof(buffer), " errno=");
    cursor = m9_append_unsigned(buffer, cursor, sizeof(buffer),
                                (uint64_t)(unsigned int)host_errno);
    cursor = m9_append_literal(buffer, cursor, sizeof(buffer), " guest=");
    cursor = m9_append_literal(buffer, cursor, sizeof(buffer), guest_path);
    cursor = m9_append_literal(buffer, cursor, sizeof(buffer), " host=");
    cursor = m9_append_literal(buffer, cursor, sizeof(buffer), host_path);
    cursor = m9_append_char(buffer, cursor, sizeof(buffer), '\n');
    size_t written = cursor < sizeof(buffer) ? cursor : sizeof(buffer);
    raw_write_literal(buffer, written);
}
'''
    text = replace_once(text, helper_anchor, helper, "raw write helper")

    replacements = [
        (
            '''    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_pread_bridge''',
            '''    int saved_errno = errno;
    m9_trace_path("open", guest_path, path,
                  (int64_t)result, saved_errno);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_pread_bridge''',
            "open path trace",
        ),
        (
            '''    int saved_errno = errno;
    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_fstatat_bridge''',
            '''    int saved_errno = errno;
    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    m9_trace_path(follow ? "stat" : "lstat", guest_path, path,
                  (int64_t)result, saved_errno);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_fstatat_bridge''',
            "stat path trace",
        ),
        (
            '''    int saved_errno = errno;
    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_access_bridge''',
            '''    int saved_errno = errno;
    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    m9_trace_path("fstatat", guest_path, path,
                  (int64_t)result, saved_errno);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_access_bridge''',
            "fstatat path trace",
        ),
        (
            '''    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_readlink_bridge''',
            '''    int saved_errno = errno;
    m9_trace_path("access", guest_path, path,
                  (int64_t)result, saved_errno);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
}

static int64_t host_readlink_bridge''',
            "access path trace",
        ),
    ]
    for needle, replacement, label in replacements:
        text = replace_once(text, needle, replacement, label)

    text = inject_once_in_function(
        text,
        "static int64_t host_readlink_bridge(const char *guest_path,\n",
        "static int64_t host_mmap_bridge(",
        "    int saved_errno = errno;\n",
        "    int saved_errno = errno;\n"
        "    m9_trace_path(\"readlink\", guest_path, path,\n"
        "                  (int64_t)result, saved_errno);\n",
        "readlink path trace",
    )

    required = {
        'HRT M9 PATH:': 1,
        'm9_trace_path("open"': 1,
        'm9_trace_path("stat"': 0,
        'm9_trace_path(follow ? "stat" : "lstat"': 1,
        'm9_trace_path("fstatat"': 1,
        'm9_trace_path("access"': 1,
        'm9_trace_path("readlink"': 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"path trace marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
