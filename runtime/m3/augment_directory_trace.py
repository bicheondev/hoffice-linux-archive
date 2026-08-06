#!/usr/bin/env python3
"""Inject async-signal-safe getdents64 diagnostics into a generated bridge."""
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

    helper_anchor = '''    raw_write_literal(buffer, cursor);
}

__attribute__((noreturn))
static void crash_signal_handler'''
    helper = r'''    raw_write_literal(buffer, cursor);
}

static void raw_trace_directory(const char *stage, int fd,
                                int64_t result, uint64_t position,
                                uint64_t record_size,
                                uint64_t name_length,
                                uint64_t output_size,
                                const unsigned char *name) {
    char buffer[320];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "hrt-m3: getdents stage=");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), stage);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " fd=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)fd);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " result=");
    if (result < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-result));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)result);
    }
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " pos=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), position);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " reclen=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), record_size);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " namlen=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), name_length);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " output=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), output_size);
    if (name != NULL && name_length != 0u) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " name=");
        uint64_t limit = name_length < 96u ? name_length : 96u;
        for (uint64_t index = 0u; index < limit && cursor < sizeof(buffer);
             ++index) {
            unsigned char byte = name[index];
            buffer[cursor++] = byte >= 32u && byte <= 126u ? (char)byte : '?';
        }
    }
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor);
}

__attribute__((noreturn))
static void crash_signal_handler'''
    text = replace_once(text, helper_anchor, helper,
                        "directory trace helper")

    raw_anchor = '''    restore_guest_context(guest);

    if (host_result < 0) {
        return -(int64_t)linux_errno_from_host((int)-host_result);
    }
'''
    raw_replacement = '''    restore_guest_context(guest);
    raw_trace_directory("host", fd, host_result, (uint64_t)position,
                        0u, 0u, 0u, NULL);

    if (host_result < 0) {
        int64_t translated =
            -(int64_t)linux_errno_from_host((int)-host_result);
        raw_trace_directory("host-error", fd, translated,
                            (uint64_t)position, 0u, 0u, 0u, NULL);
        return translated;
    }
'''
    text = replace_once(text, raw_anchor, raw_replacement,
                        "raw getdirentries result")

    record_anchor = '''        const uint16_t name_length = load_u16(entry + 18u);
        const uint8_t host_type = entry[20u];

        if (host_record_size < M3_DARWIN_DIRENT_HEADER_SIZE + 1u ||
'''
    record_replacement = '''        const uint16_t name_length = load_u16(entry + 18u);
        const uint8_t host_type = entry[20u];
        raw_trace_directory("record", fd, (int64_t)host_size,
                            seek_offset, host_record_size, name_length,
                            output_cursor,
                            entry + M3_DARWIN_DIRENT_HEADER_SIZE);

        if (host_record_size < M3_DARWIN_DIRENT_HEADER_SIZE + 1u ||
'''
    text = replace_once(text, record_anchor, record_replacement,
                        "Darwin record trace")

    return_anchor = '''    return (int64_t)output_cursor;
}

static int64_t bridge_prctl'''
    return_replacement = '''    raw_trace_directory("return", fd, (int64_t)output_cursor,
                        (uint64_t)position, 0u, 0u, output_cursor, NULL);
    return (int64_t)output_cursor;
}

static int64_t bridge_prctl'''
    text = replace_once(text, return_anchor, return_replacement,
                        "getdents return trace")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
