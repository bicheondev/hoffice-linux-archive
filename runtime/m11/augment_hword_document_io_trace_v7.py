#!/usr/bin/env python3
"""Resolve the direct HWord caller that supplies an empty file-classifier path.

The canonical frame-chain replay identifies the repeated empty ``fopen`` at
``libHwordApp.so`` file offset ``0xe15e32``.  That address is the instruction
immediately after the call to ``fopen`` inside the stripped classifier function
beginning at file offset ``0xe15d10``.

Static disassembly proves the classifier prologue is exactly six register
pushes followed by ``sub rsp, 0xb38``.  At the ``fopen`` call, its caller return
address is therefore stored ``0xb68`` bytes above the classifier's RSP.  The
canonical libc ``fopen`` frame pointer is sixteen bytes below that RSP, making
the caller slot ``frame_rbp + 0xb78``.

This fail-closed diagnostic pass runs the literal-safe v6 generator, recognizes
only the exact HWord mapping and ``0xe15e32`` return, validates the derived slot
inside the already bounded 64 KiB guest stack window, and emits the real direct
caller as ``HRT M11 CLASSIFIERCTX``.  No arbitrary mapped stack word is credited
as a caller and no guest binary is modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v6.py"
    )
    if not generator.is_file():
        raise SystemExit(f"literal-safe frame tracer not found: {generator}")

    with tempfile.TemporaryDirectory(prefix="hrt-m11-docio-v7-") as temporary:
        intermediate = Path(temporary) / "syscall_bridge_framectx.c"
        subprocess.run(
            [sys.executable, str(generator), str(args.source), str(intermediate)],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M11 CLASSIFIERCTX:" in text:
        raise SystemExit("M11 classifier-caller tracing is already present")

    text = replace_once(
        text,
        "#define M11_DOCIO_FRAME_STACK_WINDOW UINT64_C(0x10000)\n",
        "#define M11_DOCIO_FRAME_STACK_WINDOW UINT64_C(0x10000)\n"
        "#define M11_HWORD_CLASSIFIER_FOPEN_RETURN UINT64_C(0xe15e32)\n"
        "#define M11_HWORD_CLASSIFIER_SAVED_RBP_DELTA UINT64_C(0xb50)\n"
        "#define M11_HWORD_CLASSIFIER_CALLER_RETURN_DELTA UINT64_C(0xb78)\n",
        "classifier caller constants",
    )

    helper_anchor = '''static void m11_docio_note_open(int fd, const char *guest_path,
'''
    helper_replacement = r'''static int m11_docio_path_equals(const char *left,
                                  const char *right) {
    if (left == NULL || right == NULL) return 0;
    for (size_t index = 0u; index < M11_DOCIO_GUEST_PATH_BYTES; ++index) {
        const unsigned char a = (unsigned char)left[index];
        const unsigned char b = (unsigned char)right[index];
        if (a != b) return 0;
        if (a == 0u) return 1;
    }
    return 0;
}

static void m11_docio_emit_classifier_context(
    const M11OpenContext *context) {
    static const char hword_app_path[] =
        "/opt/hnc/hoffice11/Bin/libHwordApp.so";
    const sig_atomic_t stage = g_m11_docio_stage;
    if (context == NULL || stage <= 0)
        return;

    const uint64_t stack_lower = context->syscall_rsp;
    const uint64_t stack_upper =
        stack_lower <= UINT64_MAX - M11_DOCIO_FRAME_STACK_WINDOW
            ? stack_lower + M11_DOCIO_FRAME_STACK_WINDOW
            : UINT64_MAX;

    for (unsigned int index = 0u;
         index < context->frame_count && index < M11_DOCIO_FRAME_COUNT;
         ++index) {
        uint64_t return_file_offset = 0u;
        const M11DocumentMap *mapping = m11_docio_resolve_address(
            context->frame_return_address[index], &return_file_offset);
        if (mapping == NULL ||
            return_file_offset != M11_HWORD_CLASSIFIER_FOPEN_RETURN ||
            !m11_docio_path_equals(mapping->guest_path, hword_app_path)) {
            continue;
        }

        const uint64_t frame = context->frame_pointer[index];
        if (frame > UINT64_MAX - M11_HWORD_CLASSIFIER_CALLER_RETURN_DELTA -
                        sizeof(uint64_t)) {
            return;
        }
        const uint64_t saved_rbp_slot =
            frame + M11_HWORD_CLASSIFIER_SAVED_RBP_DELTA;
        const uint64_t caller_return_slot =
            frame + M11_HWORD_CLASSIFIER_CALLER_RETURN_DELTA;
        if (saved_rbp_slot < stack_lower || caller_return_slot < stack_lower ||
            saved_rbp_slot > stack_upper - sizeof(uint64_t) ||
            caller_return_slot > stack_upper - sizeof(uint64_t)) {
            return;
        }

        const uint64_t saved_caller_rbp =
            *(const uint64_t *)(uintptr_t)saved_rbp_slot;
        const uint64_t caller_return =
            *(const uint64_t *)(uintptr_t)caller_return_slot;

        char buffer[1024];
        size_t cursor = 0u;
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      "HRT M11 CLASSIFIERCTX: stage=");
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(unsigned int)stage);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " frame-index=");
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), index);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " fopen-return=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  context->frame_return_address[index]);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " fopen-return-file-offset=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  return_file_offset);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " path-pointer=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  context->path_pointer);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " saved-caller-rbp-slot=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  saved_rbp_slot);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " saved-caller-rbp=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  saved_caller_rbp);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " caller-return-slot=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  caller_return_slot);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " caller-return=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  caller_return);
        cursor = m11_docio_append_resolution(
            buffer, cursor, sizeof(buffer), "caller-return", caller_return);
        if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
        raw_write_literal(
            buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
        return;
    }
}

static void m11_docio_note_open(int fd, const char *guest_path,
'''
    text = replace_once(text, helper_anchor, helper_replacement,
                        "classifier caller helper insertion")

    text = replace_once(
        text,
        '''    m11_docio_emit_open_context(open_context);
    m11_docio_emit_frame_context(open_context);
}
''',
        '''    m11_docio_emit_open_context(open_context);
    m11_docio_emit_frame_context(open_context);
    m11_docio_emit_classifier_context(open_context);
}
''',
        "classifier caller emission",
    )

    required = {
        "HRT M11 CLASSIFIERCTX:": 1,
        "M11_HWORD_CLASSIFIER_FOPEN_RETURN UINT64_C(0xe15e32)": 1,
        "M11_HWORD_CLASSIFIER_SAVED_RBP_DELTA UINT64_C(0xb50)": 1,
        "M11_HWORD_CLASSIFIER_CALLER_RETURN_DELTA UINT64_C(0xb78)": 1,
        "m11_docio_emit_classifier_context(": 2,
        "m11_docio_path_equals(": 2,
        "caller-return-file-offset=": 0,
        "m11_docio_append_resolution(": 5,
        "HRT M11 FRAMECTX:": 1,
        "M11_DOCIO_STACK_WORD_COUNT 32u": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"classifier-caller marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
