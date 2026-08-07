#!/usr/bin/env python3
"""Add bounded executable-file mapping diagnostics to the mature bridge.

The dynamic Linux loader maps shared-library PT_LOAD segments through the
runtime's mmap bridge.  Recording only successful file-backed executable
mappings gives the one-shot exception probe enough information to attribute a
return address to an exact guest object and file offset without LD_PRELOAD,
ptrace, or a VM.
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
    if "HRT M9 MAP:" in text:
        raise SystemExit("M9 executable mmap tracing is already present")

    define_anchor = "#define DARWIN_SYS_GETPID UINT64_C(20)\n"
    text = replace_once(
        text,
        define_anchor,
        define_anchor +
        "#ifndef F_GETPATH\n"
        "#define F_GETPATH 50\n"
        "#endif\n"
        "#define M9_EXEC_MAP_TRACE_LIMIT 1024u\n",
        "Darwin F_GETPATH constant",
    )

    helper_anchor = '''static void raw_write_literal(const char *message, size_t length) {
    (void)raw_bsd_syscall3(DARWIN_SYS_WRITE, STDERR_FILENO,
                           (uint64_t)(uintptr_t)message, length);
}
'''
    helper = helper_anchor + r'''
static unsigned int g_m9_exec_map_trace_count;

static size_t m9_map_append_char(char *buffer, size_t cursor,
                                 size_t capacity, char value) {
    if (cursor < capacity) buffer[cursor] = value;
    return cursor + 1u;
}

static size_t m9_map_append_literal(char *buffer, size_t cursor,
                                    size_t capacity, const char *value) {
    if (value == NULL) value = "(null)";
    for (size_t index = 0u; value[index] != '\0'; ++index) {
        cursor = m9_map_append_char(buffer, cursor, capacity, value[index]);
    }
    return cursor;
}

static size_t m9_map_append_unsigned(char *buffer, size_t cursor,
                                     size_t capacity, uint64_t value) {
    char digits[24];
    size_t count = 0u;
    do {
        digits[count++] = (char)('0' + value % 10u);
        value /= 10u;
    } while (value != 0u && count < sizeof(digits));
    while (count != 0u) {
        cursor = m9_map_append_char(buffer, cursor, capacity,
                                    digits[--count]);
    }
    return cursor;
}

static size_t m9_map_append_hex(char *buffer, size_t cursor,
                                size_t capacity, uint64_t value) {
    static const char digits[] = "0123456789abcdef";
    cursor = m9_map_append_literal(buffer, cursor, capacity, "0x");
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned int nibble = (unsigned int)((value >> shift) & 0x0fu);
        if (nibble != 0u || started != 0 || shift == 0) {
            cursor = m9_map_append_char(buffer, cursor, capacity,
                                        digits[nibble]);
            started = 1;
        }
    }
    return cursor;
}

static void m9_trace_executable_mapping(void *mapping, size_t length,
                                        uint64_t file_offset, int fd,
                                        int protection) {
    if (mapping == MAP_FAILED || fd < 0 || length == 0u ||
        (protection & PROT_EXEC) == 0 ||
        g_m9_exec_map_trace_count >= M9_EXEC_MAP_TRACE_LIMIT) {
        return;
    }
    ++g_m9_exec_map_trace_count;

    char path[PATH_MAX];
    memset(path, 0, sizeof(path));
    if (fcntl(fd, F_GETPATH, path) != 0) {
        (void)strlcpy(path, "(unresolved-fd)", sizeof(path));
    }

    char buffer[PATH_MAX + 256];
    size_t cursor = 0u;
    cursor = m9_map_append_literal(buffer, cursor, sizeof(buffer),
                                   "HRT M9 MAP: start=");
    cursor = m9_map_append_hex(buffer, cursor, sizeof(buffer),
                               (uint64_t)(uintptr_t)mapping);
    cursor = m9_map_append_literal(buffer, cursor, sizeof(buffer), " end=");
    cursor = m9_map_append_hex(buffer, cursor, sizeof(buffer),
                               (uint64_t)((uintptr_t)mapping + length));
    cursor = m9_map_append_literal(buffer, cursor, sizeof(buffer), " offset=");
    cursor = m9_map_append_hex(buffer, cursor, sizeof(buffer), file_offset);
    cursor = m9_map_append_literal(buffer, cursor, sizeof(buffer), " fd=");
    cursor = m9_map_append_unsigned(buffer, cursor, sizeof(buffer),
                                    (uint64_t)(unsigned int)fd);
    cursor = m9_map_append_literal(buffer, cursor, sizeof(buffer), " path=");
    cursor = m9_map_append_literal(buffer, cursor, sizeof(buffer), path);
    cursor = m9_map_append_char(buffer, cursor, sizeof(buffer), '\n');
    size_t written = cursor < sizeof(buffer) ? cursor : sizeof(buffer);
    raw_write_literal(buffer, written);
}
'''
    text = replace_once(text, helper_anchor, helper,
                        "raw write helper")

    mmap_anchor = '''    if (result != MAP_FAILED && needs_exec_patch) {
        size_t rewritten_fs = 0u;
        (void)patch_guest_code(result, length, &rewritten_fs);
        if (mprotect(result, length, protection) != 0) {
            saved_errno = errno;
            (void)munmap(result, length);
            result = MAP_FAILED;
        }
    }
    restore_guest_context(guest);
'''
    mmap_replacement = '''    if (result != MAP_FAILED && needs_exec_patch) {
        size_t rewritten_fs = 0u;
        (void)patch_guest_code(result, length, &rewritten_fs);
        if (mprotect(result, length, protection) != 0) {
            saved_errno = errno;
            (void)munmap(result, length);
            result = MAP_FAILED;
        }
    }
    if (result != MAP_FAILED) {
        m9_trace_executable_mapping(result, length, offset, fd, protection);
    }
    restore_guest_context(guest);
'''
    text = replace_once(text, mmap_anchor, mmap_replacement,
                        "successful executable mmap trace")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
