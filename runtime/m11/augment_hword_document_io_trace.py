#!/usr/bin/env python3
"""Add a stage-gated HWord document I/O trace to the final host bridge.

The exact product-closure replay now materializes HWord's native error dialog,
but that dialog reports a damaged or unsupported file before an editor view is
created.  The older M9 path trace is intentionally startup-oriented: it emits
all failures plus successful font/database paths and can exhaust its budget
before the real New-document click.

This transform is applied after every syscall/thread augmentation.  It adds a
small exported stage marker called by the AppKit input driver immediately
before each staged action, keeps a fixed descriptor-to-path table even before
tracing is armed, and records the following only after stage 1 begins:

* open/openat results, flags, guest paths, and Darwin-resolved paths;
* read, write, pread, lseek, fstat, mmap, and close activity for tracked fds;
* stat/lstat, fstatat, access, readlink, and readlinkat path results; and
* explicit stage transitions.

All storage is static, every message uses the existing raw Darwin write bridge,
and no allocation or stdio occurs from the SIGILL syscall path.  Source edits
are function-scoped and fail closed.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def replace_in_function(
    text: str,
    function_start: str,
    next_function_start: str,
    needle: str,
    replacement: str,
    label: str,
) -> str:
    start_count = text.count(function_start)
    if start_count != 1:
        raise SystemExit(
            f"{label}: expected one function start, found {start_count}")
    start = text.index(function_start)
    end = text.find(next_function_start, start + len(function_start))
    if end < 0:
        raise SystemExit(f"{label}: next function start not found")
    function = text[start:end]
    count = function.count(needle)
    if count != 1:
        tail = function[-2400:].replace("\n", "\\n")
        raise SystemExit(
            f"{label}: expected one in-function anchor, found {count}; "
            f"function-tail={tail}")
    function = function.replace(needle, replacement, 1)
    return text[:start] + function + text[end:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M11 DOCIO:" in text:
        raise SystemExit("M11 HWord document I/O tracing is already present")

    helper_anchor = (
        "static int64_t host_read_bridge(int fd, void *buffer, size_t size) {\n"
    )
    helpers = r'''#define M11_DOCIO_FD_LIMIT 1024u
#define M11_DOCIO_GUEST_PATH_BYTES 384u
#define M11_DOCIO_HOST_PATH_BYTES 768u
#define M11_DOCIO_TRACE_LIMIT 8192u

typedef struct {
    int active;
    int fd;
    uint64_t open_flags;
    char guest_path[M11_DOCIO_GUEST_PATH_BYTES];
    char host_path[M11_DOCIO_HOST_PATH_BYTES];
} M11DocumentFd;

static M11DocumentFd g_m11_document_fds[M11_DOCIO_FD_LIMIT];
static volatile sig_atomic_t g_m11_docio_stage;
static unsigned int g_m11_docio_trace_count;

static size_t m11_docio_append_signed(char *buffer, size_t cursor,
                                      size_t capacity, int64_t value) {
    if (value < 0) {
        if (cursor < capacity) buffer[cursor++] = '-';
        return trace_append_decimal(
            buffer, cursor, capacity,
            (uint64_t)(-(value + 1)) + UINT64_C(1));
    }
    return trace_append_decimal(buffer, cursor, capacity, (uint64_t)value);
}

static void m11_docio_copy_path(char *destination, size_t capacity,
                                const char *source) {
    if (destination == NULL || capacity == 0u) return;
    if (source == NULL) source = "(null)";
    size_t index = 0u;
    while (index + 1u < capacity && source[index] != '\0') {
        destination[index] = source[index];
        ++index;
    }
    destination[index] = '\0';
}

static M11DocumentFd *m11_docio_slot(int fd) {
    if (fd < 0 || (uint64_t)(unsigned int)fd >= M11_DOCIO_FD_LIMIT)
        return NULL;
    return &g_m11_document_fds[(unsigned int)fd];
}

static M11DocumentFd *m11_docio_record(int fd) {
    M11DocumentFd *record = m11_docio_slot(fd);
    if (record == NULL || !record->active || record->fd != fd)
        return NULL;
    return record;
}

static void m11_docio_emit(const char *operation, int fd, int64_t result,
                           uint64_t size, int64_t offset, uint64_t auxiliary,
                           const char *guest_path, const char *host_path) {
    const sig_atomic_t stage = g_m11_docio_stage;
    if (stage <= 0 || g_m11_docio_trace_count >= M11_DOCIO_TRACE_LIMIT)
        return;
    ++g_m11_docio_trace_count;

    char buffer[1536];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M11 DOCIO: stage=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)stage);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " op=");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), operation);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " fd=");
    cursor = m11_docio_append_signed(buffer, cursor, sizeof(buffer), fd);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " result=");
    cursor = m11_docio_append_signed(buffer, cursor, sizeof(buffer), result);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " size=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), size);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " offset=");
    cursor = m11_docio_append_signed(buffer, cursor, sizeof(buffer), offset);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " aux=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), auxiliary);
    if (guest_path != NULL) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " guest=");
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      guest_path);
    }
    if (host_path != NULL) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " host=");
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      host_path);
    }
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

void hrt_m11_docio_mark_stage(unsigned int stage) {
    if (stage == 0u) return;
    if ((sig_atomic_t)stage > g_m11_docio_stage)
        g_m11_docio_stage = (sig_atomic_t)stage;

    char buffer[96];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M11 DOCIO: armed stage=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), stage);
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor);
}

static void m11_docio_note_open(int fd, const char *guest_path,
                                const char *translated_path,
                                uint64_t flags, uint64_t mode,
                                int saved_errno) {
    char resolved[M11_DOCIO_HOST_PATH_BYTES];
    resolved[0] = '\0';
#ifdef F_GETPATH
    if (fd >= 0) {
        errno = 0;
        if (fcntl(fd, F_GETPATH, resolved) != 0)
            resolved[0] = '\0';
    }
#endif
    const char *host_path = resolved[0] != '\0'
        ? resolved : translated_path;

    if (fd >= 0) {
        M11DocumentFd *record = m11_docio_slot(fd);
        if (record != NULL) {
            memset(record, 0, sizeof(*record));
            record->active = 1;
            record->fd = fd;
            record->open_flags = flags;
            m11_docio_copy_path(record->guest_path,
                                sizeof(record->guest_path), guest_path);
            m11_docio_copy_path(record->host_path,
                                sizeof(record->host_path), host_path);
        }
    }

    const int64_t result = fd >= 0
        ? (int64_t)fd : -(int64_t)linux_errno_from_host(saved_errno);
    m11_docio_emit("open", fd, result, mode, 0, flags,
                   guest_path, host_path);
}

static void m11_docio_trace_fd(const char *operation, int fd, int64_t result,
                               uint64_t size, int64_t offset,
                               uint64_t auxiliary) {
    M11DocumentFd *record = m11_docio_record(fd);
    if (record == NULL) return;
    m11_docio_emit(operation, fd, result, size, offset, auxiliary,
                   record->guest_path, record->host_path);
}

static void m11_docio_forget_fd(int fd) {
    M11DocumentFd *record = m11_docio_record(fd);
    if (record != NULL) memset(record, 0, sizeof(*record));
}

static void m11_docio_trace_path(const char *operation,
                                 const char *guest_path,
                                 const char *host_path,
                                 int64_t host_result,
                                 int saved_errno,
                                 uint64_t auxiliary) {
    const int64_t result = host_result < 0
        ? -(int64_t)linux_errno_from_host(saved_errno) : host_result;
    m11_docio_emit(operation, -1, result, 0u, 0, auxiliary,
                   guest_path, host_path);
}

'''
    text = replace_once(text, helper_anchor, helpers + helper_anchor,
                        "document I/O helper insertion")

    read_tail = '''    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
'''
    read_replacement = '''    int saved_errno = errno;
    restore_guest_context(guest);
    const int64_t linux_result =
        linux_host_result((int64_t)result, saved_errno);
    m11_docio_trace_fd("read", fd, linux_result, size, 0, 0u);
    return linux_result;
'''
    text = replace_in_function(
        text,
        "static int64_t host_read_bridge(int fd, void *buffer, size_t size) {\n",
        "static int64_t host_write_bridge(int fd, const void *buffer, size_t size) {\n",
        read_tail, read_replacement, "read descriptor trace")

    write_replacement = '''    int saved_errno = errno;
    restore_guest_context(guest);
    const int64_t linux_result =
        linux_host_result((int64_t)result, saved_errno);
    m11_docio_trace_fd("write", fd, linux_result, size, 0, 0u);
    return linux_result;
'''
    text = replace_in_function(
        text,
        "static int64_t host_write_bridge(int fd, const void *buffer, size_t size) {\n",
        "static int64_t host_close_bridge(int fd) {\n",
        read_tail, write_replacement, "write descriptor trace")

    close_tail = '''    int saved_errno = errno;
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
'''
    close_replacement = '''    int saved_errno = errno;
    restore_guest_context(guest);
    const int64_t linux_result =
        linux_host_result((int64_t)result, saved_errno);
    m11_docio_trace_fd("close", fd, linux_result, 0u, 0, 0u);
    if (linux_result == 0) m11_docio_forget_fd(fd);
    return linux_result;
'''
    text = replace_in_function(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        "static int64_t host_open_bridge(int directory_fd, const char *guest_path,\n",
        close_tail, close_replacement, "close descriptor trace")

    open_anchor = '''    m9_trace_path("open", guest_path, path,
                  (int64_t)result, saved_errno);
'''
    open_replacement = open_anchor + '''    m11_docio_note_open(result, guest_path, path,
                         flags, mode, saved_errno);
'''
    text = replace_once(text, open_anchor, open_replacement,
                        "open descriptor tracking")

    pread_replacement = '''    int saved_errno = errno;
    restore_guest_context(guest);
    const int64_t linux_result =
        linux_host_result((int64_t)result, saved_errno);
    m11_docio_trace_fd("pread", fd, linux_result, size, offset, 0u);
    return linux_result;
'''
    text = replace_in_function(
        text,
        "static int64_t host_pread_bridge(int fd, void *buffer, size_t size,\n",
        "static int64_t host_lseek_bridge(int fd, int64_t offset, int whence) {\n",
        read_tail, pread_replacement, "pread descriptor trace")

    lseek_replacement = '''    int saved_errno = errno;
    restore_guest_context(guest);
    const int64_t linux_result =
        linux_host_result((int64_t)result, saved_errno);
    m11_docio_trace_fd("lseek", fd, linux_result, 0u, offset,
                       (uint64_t)(unsigned int)whence);
    return linux_result;
'''
    text = replace_in_function(
        text,
        "static int64_t host_lseek_bridge(int fd, int64_t offset, int whence) {\n",
        "static int64_t host_fstat_bridge(int fd, LinuxStat *guest_stat) {\n",
        read_tail, lseek_replacement, "lseek descriptor trace")

    fstat_tail = '''    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    restore_guest_context(guest);
    return linux_host_result((int64_t)result, saved_errno);
'''
    fstat_replacement = '''    if (result == 0) linux_stat_from_host(guest_stat, &host_stat);
    restore_guest_context(guest);
    const int64_t linux_result =
        linux_host_result((int64_t)result, saved_errno);
    m11_docio_trace_fd("fstat", fd, linux_result,
                       result == 0 ? (uint64_t)host_stat.st_size : 0u,
                       0, 0u);
    return linux_result;
'''
    text = replace_in_function(
        text,
        "static int64_t host_fstat_bridge(int fd, LinuxStat *guest_stat) {\n",
        "static int64_t host_path_stat_bridge(const char *guest_path,\n",
        fstat_tail, fstat_replacement, "fstat descriptor trace")

    path_replacements = [
        (
            '''    m9_trace_path(follow ? "stat" : "lstat", guest_path, path,
                  (int64_t)result, saved_errno);
''',
            '''    m9_trace_path(follow ? "stat" : "lstat", guest_path, path,
                  (int64_t)result, saved_errno);
    m11_docio_trace_path(follow ? "stat" : "lstat", guest_path, path,
                         (int64_t)result, saved_errno, 0u);
''',
            "stat path trace",
        ),
        (
            '''    m9_trace_path("fstatat", guest_path, path,
                  (int64_t)result, saved_errno);
''',
            '''    m9_trace_path("fstatat", guest_path, path,
                  (int64_t)result, saved_errno);
    m11_docio_trace_path("fstatat", guest_path, path,
                         (int64_t)result, saved_errno, flags);
''',
            "fstatat path trace",
        ),
        (
            '''    m9_trace_path("access", guest_path, path,
                  (int64_t)result, saved_errno);
''',
            '''    m9_trace_path("access", guest_path, path,
                  (int64_t)result, saved_errno);
    m11_docio_trace_path("access", guest_path, path,
                         (int64_t)result, saved_errno,
                         ((uint64_t)(unsigned int)mode << 32) | flags);
''',
            "access path trace",
        ),
        (
            '''    m9_trace_path("readlink", guest_path, path,
                  (int64_t)result, saved_errno);
''',
            '''    m9_trace_path("readlink", guest_path, path,
                  (int64_t)result, saved_errno);
    m11_docio_trace_path("readlink", guest_path, path,
                         (int64_t)result, saved_errno, (uint64_t)size);
''',
            "readlink path trace",
        ),
        (
            '''    m9_trace_path("readlinkat", guest_path, path,
                  (int64_t)result, saved_errno);
''',
            '''    m9_trace_path("readlinkat", guest_path, path,
                  (int64_t)result, saved_errno);
    m11_docio_trace_path("readlinkat", guest_path, path,
                         (int64_t)result, saved_errno,
                         ((uint64_t)(unsigned int)directory_fd << 32) |
                             (uint64_t)size);
''',
            "readlinkat path trace",
        ),
    ]
    for needle, replacement, label in path_replacements:
        text = replace_once(text, needle, replacement, label)

    mmap_tail = '''    restore_guest_context(guest);
    if (result == MAP_FAILED) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }
    return (int64_t)(uintptr_t)result;
'''
    mmap_replacement = '''    restore_guest_context(guest);
    const int64_t linux_result = result == MAP_FAILED
        ? -(int64_t)linux_errno_from_host(saved_errno)
        : (int64_t)(uintptr_t)result;
    m11_docio_trace_fd("mmap", fd, linux_result, (uint64_t)length,
                       (int64_t)offset,
                       ((linux_protection & UINT64_C(0xffffffff)) << 32) |
                           (linux_flags & UINT64_C(0xffffffff)));
    return linux_result;
'''
    text = replace_in_function(
        text,
        "static int64_t host_mmap_bridge(uintptr_t address, size_t length,\n",
        "static int64_t host_mprotect_bridge(void *address, size_t length,\n",
        mmap_tail, mmap_replacement, "mmap descriptor trace")

    required = {
        "HRT M11 DOCIO:": 2,
        "hrt_m11_docio_mark_stage(": 1,
        "m11_docio_note_open(": 2,
        "m11_docio_trace_fd(": 8,
        "m11_docio_trace_path(": 6,
        'm11_docio_trace_fd("read"': 1,
        'm11_docio_trace_fd("write"': 1,
        'm11_docio_trace_fd("close"': 1,
        'm11_docio_trace_fd("pread"': 1,
        'm11_docio_trace_fd("lseek"': 1,
        'm11_docio_trace_fd("fstat"': 1,
        'm11_docio_trace_fd("mmap"': 1,
        "M11_DOCIO_TRACE_LIMIT 8192u": 1,
        'm9_trace_path("open"': 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"document-I/O marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
