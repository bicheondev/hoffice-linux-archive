#!/usr/bin/env python3
"""Add callsite and executable-map context to the stage-gated HWord I/O trace.

The exact product-closure replay proves that the official 7,307-byte HWDT
archive is copied and traversed successfully.  The closest direct precursor to
the native read-error dialog is instead a sequence of ``openat(AT_FDCWD, "",
...)`` failures.  The v2 trace records the empty paths but not the guest code
that supplied them.

This pass runs the reviewed brace-scoped v2 generator and then:

* executes Darwin ``F_GETPATH`` only after restoring the host GS/TSD context;
* records file-backed executable ``mmap`` ranges before tracing is armed;
* captures syscall RIP/RSP/RBP, four guest stack words, dirfd and path pointer
  for every Linux ``open``/``openat`` boundary;
* resolves those code addresses to the most recent executable guest mapping
  and file offset; and
* emits a bounded ``HRT M11 OPENCTX`` line beside the existing open trace.

The map and descriptor tables are static.  Address capture performs no host
libc call from the SIGILL path, and all edits use exact, fail-closed anchors.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


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

    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v2.py"
    )
    if not generator.is_file():
        raise SystemExit(f"document-I/O v2 generator not found: {generator}")

    with tempfile.TemporaryDirectory(prefix="hrt-m11-docio-v3-") as temporary:
        intermediate = Path(temporary) / "syscall_bridge_docio_v2.c"
        subprocess.run(
            [sys.executable, str(generator), str(args.source), str(intermediate)],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M11 OPENCTX:" in text:
        raise SystemExit("M11 open-callsite tracing is already present")

    constants_anchor = '''#define M11_DOCIO_TRACE_LIMIT 8192u

typedef struct {
'''
    constants_replacement = '''#define M11_DOCIO_TRACE_LIMIT 8192u
#define M11_DOCIO_MAP_LIMIT 4096u
#define M11_DOCIO_STACK_WORD_COUNT 4u

typedef struct {
'''
    text = replace_once(text, constants_anchor, constants_replacement,
                        "open-callsite constants")

    types_anchor = '''} M11DocumentFd;

static M11DocumentFd g_m11_document_fds[M11_DOCIO_FD_LIMIT];
static volatile sig_atomic_t g_m11_docio_stage;
static unsigned int g_m11_docio_trace_count;
'''
    types_replacement = '''} M11DocumentFd;

typedef struct {
    uintptr_t start;
    uintptr_t end;
    uint64_t file_offset;
    uint64_t linux_protection;
    char guest_path[M11_DOCIO_GUEST_PATH_BYTES];
} M11DocumentMap;

typedef struct {
    uint64_t syscall_number;
    uint64_t syscall_rip;
    uint64_t syscall_rsp;
    uint64_t syscall_rbp;
    int64_t directory_fd;
    uint64_t path_pointer;
    uint64_t stack_words[M11_DOCIO_STACK_WORD_COUNT];
} M11OpenContext;

static M11DocumentFd g_m11_document_fds[M11_DOCIO_FD_LIMIT];
static M11DocumentMap g_m11_document_maps[M11_DOCIO_MAP_LIMIT];
static unsigned int g_m11_document_map_count;
static volatile sig_atomic_t g_m11_docio_stage;
static unsigned int g_m11_docio_trace_count;
'''
    text = replace_once(text, types_anchor, types_replacement,
                        "open-callsite types")

    capture_anchor = '''static M11DocumentFd *m11_docio_slot(int fd) {
'''
    capture_helpers = r'''static uint64_t m11_docio_stack_word(uint64_t stack_pointer,
                                      unsigned int index) {
    if (index >= M11_DOCIO_STACK_WORD_COUNT ||
        stack_pointer < UINT64_C(0x10000)) {
        return 0u;
    }
    const uint64_t offset = (uint64_t)index * sizeof(uint64_t);
    if (stack_pointer > UINT64_MAX - offset - sizeof(uint64_t))
        return 0u;
    return *(const uint64_t *)(uintptr_t)(stack_pointer + offset);
}

static M11OpenContext m11_docio_capture_open_context(
    const x86_thread_state64_t *state, int directory_fd,
    uint64_t path_pointer) {
    M11OpenContext context;
    memset(&context, 0, sizeof(context));
    if (state == NULL) return context;
    context.syscall_number = state->__rax;
    context.syscall_rip = state->__rip;
    context.syscall_rsp = state->__rsp;
    context.syscall_rbp = state->__rbp;
    context.directory_fd = directory_fd;
    context.path_pointer = path_pointer;
    for (unsigned int index = 0u;
         index < M11_DOCIO_STACK_WORD_COUNT; ++index) {
        context.stack_words[index] =
            m11_docio_stack_word(state->__rsp, index);
    }
    return context;
}

static const M11DocumentMap *m11_docio_resolve_address(
    uint64_t address, uint64_t *file_offset) {
    if (file_offset != NULL) *file_offset = 0u;
    if (address == 0u) return NULL;
    for (unsigned int index = g_m11_document_map_count;
         index > 0u; --index) {
        const M11DocumentMap *mapping = &g_m11_document_maps[index - 1u];
        if ((uintptr_t)address >= mapping->start &&
            (uintptr_t)address < mapping->end) {
            if (file_offset != NULL) {
                *file_offset = mapping->file_offset +
                    (uint64_t)((uintptr_t)address - mapping->start);
            }
            return mapping;
        }
    }
    return NULL;
}

static size_t m11_docio_append_resolution(
    char *buffer, size_t cursor, size_t capacity,
    const char *label, uint64_t address) {
    uint64_t file_offset = 0u;
    const M11DocumentMap *mapping =
        m11_docio_resolve_address(address, &file_offset);
    cursor = trace_append_literal(buffer, cursor, capacity, " ");
    cursor = trace_append_literal(buffer, cursor, capacity, label);
    cursor = trace_append_literal(buffer, cursor, capacity, "-object=");
    cursor = trace_append_literal(
        buffer, cursor, capacity,
        mapping != NULL ? mapping->guest_path : "(unmapped)");
    if (mapping != NULL) {
        cursor = trace_append_literal(buffer, cursor, capacity, " ");
        cursor = trace_append_literal(buffer, cursor, capacity, label);
        cursor = trace_append_literal(buffer, cursor, capacity,
                                      "-file-offset=");
        cursor = trace_append_hex(buffer, cursor, capacity, file_offset);
    }
    return cursor;
}

static M11DocumentFd *m11_docio_slot(int fd) {
'''
    text = replace_once(text, capture_anchor, capture_helpers,
                        "open context capture helpers")

    context_anchor = '''static void m11_docio_note_open(int fd, const char *guest_path,
'''
    context_helpers = r'''static void m11_docio_emit_open_context(
    const M11OpenContext *context) {
    const sig_atomic_t stage = g_m11_docio_stage;
    if (context == NULL || stage <= 0 ||
        g_m11_docio_trace_count >= M11_DOCIO_TRACE_LIMIT) {
        return;
    }
    ++g_m11_docio_trace_count;

    char buffer[4096];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M11 OPENCTX: stage=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)stage);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " syscall=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  context->syscall_number);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " rip=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                              context->syscall_rip);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " rsp=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                              context->syscall_rsp);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " rbp=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                              context->syscall_rbp);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " dirfd=");
    cursor = m11_docio_append_signed(buffer, cursor, sizeof(buffer),
                                     context->directory_fd);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " path-pointer=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                              context->path_pointer);
    for (unsigned int index = 0u;
         index < M11_DOCIO_STACK_WORD_COUNT; ++index) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " stack");
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), index);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer), "=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  context->stack_words[index]);
    }
    cursor = m11_docio_append_resolution(
        buffer, cursor, sizeof(buffer), "rip", context->syscall_rip);
    for (unsigned int index = 0u;
         index < M11_DOCIO_STACK_WORD_COUNT; ++index) {
        char label[16];
        size_t label_cursor = 0u;
        label_cursor = trace_append_literal(
            label, label_cursor, sizeof(label), "stack");
        label_cursor = trace_append_decimal(
            label, label_cursor, sizeof(label), index);
        if (label_cursor >= sizeof(label)) label_cursor = sizeof(label) - 1u;
        label[label_cursor] = '\0';
        cursor = m11_docio_append_resolution(
            buffer, cursor, sizeof(buffer), label,
            context->stack_words[index]);
    }
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static void m11_docio_note_open(int fd, const char *guest_path,
'''
    text = replace_once(text, context_anchor, context_helpers,
                        "open context emitter")

    note_signature_anchor = '''static void m11_docio_note_open(int fd, const char *guest_path,
                                const char *translated_path,
                                uint64_t flags, uint64_t mode,
                                int saved_errno) {
'''
    note_signature_replacement = '''static void m11_docio_note_open(int fd, const char *guest_path,
                                const char *translated_path,
                                uint64_t flags, uint64_t mode,
                                int saved_errno,
                                const M11OpenContext *open_context) {
'''
    text = replace_once(text, note_signature_anchor,
                        note_signature_replacement,
                        "open context parameter")

    fgetpath_anchor = '''#ifdef F_GETPATH
    if (fd >= 0) {
        errno = 0;
        if (fcntl(fd, F_GETPATH, resolved) != 0)
            resolved[0] = '\0';
    }
#endif
'''
    fgetpath_replacement = '''#ifdef F_GETPATH
    if (fd >= 0) {
        uintptr_t guest_context = switch_to_host_context();
        errno = 0;
        if (fcntl(fd, F_GETPATH, resolved) != 0)
            resolved[0] = '\0';
        restore_guest_context(guest_context);
    }
#endif
'''
    text = replace_once(text, fgetpath_anchor, fgetpath_replacement,
                        "F_GETPATH host context")

    note_emit_anchor = '''    m11_docio_emit("open", fd, result, mode, 0, flags,
                   guest_path, host_path);
}
'''
    note_emit_replacement = '''    m11_docio_emit("open", fd, result, mode, 0, flags,
                   guest_path, host_path);
    m11_docio_emit_open_context(open_context);
}
'''
    text = replace_once(text, note_emit_anchor, note_emit_replacement,
                        "open context emission")

    mapping_anchor = '''static int64_t host_read_bridge(int fd, void *buffer, size_t size) {
'''
    mapping_helper = r'''static void m11_docio_note_mapping(
    int fd, int64_t mapped_address, size_t length, uint64_t file_offset,
    uint64_t linux_protection) {
    if (mapped_address < 0 || fd < 0 || length == 0u ||
        (linux_protection & LINUX_PROT_EXEC) == 0u ||
        g_m11_document_map_count >= M11_DOCIO_MAP_LIMIT) {
        return;
    }
    M11DocumentFd *descriptor = m11_docio_record(fd);
    if (descriptor == NULL) return;
    const uintptr_t start = (uintptr_t)mapped_address;
    if (start > UINTPTR_MAX - length) return;

    M11DocumentMap *mapping =
        &g_m11_document_maps[g_m11_document_map_count++];
    memset(mapping, 0, sizeof(*mapping));
    mapping->start = start;
    mapping->end = start + length;
    mapping->file_offset = file_offset;
    mapping->linux_protection = linux_protection;
    m11_docio_copy_path(mapping->guest_path,
                        sizeof(mapping->guest_path),
                        descriptor->guest_path);
}

static int64_t host_read_bridge(int fd, void *buffer, size_t size) {
'''
    text = replace_once(text, mapping_anchor, mapping_helper,
                        "executable mapping recorder")

    open_bridge_anchor = '''static int64_t host_open_bridge(int directory_fd, const char *guest_path,
                                uint64_t flags, uint64_t mode) {
'''
    open_bridge_replacement = '''static int64_t host_open_bridge(int directory_fd, const char *guest_path,
                                uint64_t flags, uint64_t mode,
                                const M11OpenContext *open_context) {
'''
    text = replace_once(text, open_bridge_anchor, open_bridge_replacement,
                        "open bridge context parameter")

    note_call_anchor = '''    m11_docio_note_open(result, guest_path, path,
                         flags, mode, saved_errno);
'''
    note_call_replacement = '''    m11_docio_note_open(result, guest_path, path,
                         flags, mode, saved_errno, open_context);
'''
    text = replace_once(text, note_call_anchor, note_call_replacement,
                        "open context forwarding")

    mmap_anchor = '''    m11_docio_trace_fd("mmap", fd, linux_result, (uint64_t)length,
                       (int64_t)offset,
                       ((linux_protection & UINT64_C(0xffffffff)) << 32) |
                           (linux_flags & UINT64_C(0xffffffff)));
'''
    mmap_replacement = '''    m11_docio_note_mapping(fd, linux_result, length, offset,
                             linux_protection);
    m11_docio_trace_fd("mmap", fd, linux_result, (uint64_t)length,
                       (int64_t)offset,
                       ((linux_protection & UINT64_C(0xffffffff)) << 32) |
                           (linux_flags & UINT64_C(0xffffffff)));
'''
    text = replace_once(text, mmap_anchor, mmap_replacement,
                        "mmap executable mapping capture")

    open_case_anchor = '''        case LINUX_SYS_OPEN:
            result = host_open_bridge(LINUX_AT_FDCWD,
                                      (const char *)(uintptr_t)state->__rdi,
                                      state->__rsi, state->__rdx);
            break;
'''
    open_case_replacement = '''        case LINUX_SYS_OPEN: {
            const M11OpenContext open_context =
                m11_docio_capture_open_context(
                    state, LINUX_AT_FDCWD, state->__rdi);
            result = host_open_bridge(LINUX_AT_FDCWD,
                                      (const char *)(uintptr_t)state->__rdi,
                                      state->__rsi, state->__rdx,
                                      &open_context);
            break;
        }
'''
    text = replace_once(text, open_case_anchor, open_case_replacement,
                        "Linux open callsite capture")

    openat_case_anchor = '''        case LINUX_SYS_OPENAT:
            result = host_open_bridge(
                (int)state->__rdi,
                (const char *)(uintptr_t)state->__rsi,
                state->__rdx, state->__r10);
            break;
'''
    openat_case_replacement = '''        case LINUX_SYS_OPENAT: {
            const M11OpenContext open_context =
                m11_docio_capture_open_context(
                    state, (int)state->__rdi, state->__rsi);
            result = host_open_bridge(
                (int)state->__rdi,
                (const char *)(uintptr_t)state->__rsi,
                state->__rdx, state->__r10, &open_context);
            break;
        }
'''
    text = replace_once(text, openat_case_anchor, openat_case_replacement,
                        "Linux openat callsite capture")

    required = {
        "HRT M11 OPENCTX:": 1,
        "M11_DOCIO_MAP_LIMIT 4096u": 1,
        "M11_DOCIO_STACK_WORD_COUNT 4u": 1,
        "m11_docio_capture_open_context(": 3,
        "m11_docio_note_mapping(": 2,
        "m11_docio_resolve_address(": 2,
        "m11_docio_emit_open_context(": 2,
        "const M11OpenContext *open_context": 2,
        "restore_guest_context(guest_context);": 1,
        "case LINUX_SYS_OPEN: {": 1,
        "case LINUX_SYS_OPENAT: {": 1,
        "state, LINUX_AT_FDCWD, state->__rdi": 1,
        "state, (int)state->__rdi, state->__rsi": 1,
        "m11_docio_note_mapping(fd, linux_result": 1,
        "fcntl(fd, F_GETPATH, resolved)": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"open-callsite marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
