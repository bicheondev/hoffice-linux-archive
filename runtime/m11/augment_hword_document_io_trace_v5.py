#!/usr/bin/env python3
"""Add a bounded frame-pointer chain to the 32-word HWord open tracer.

The 32-word replay resolved a repeated ``libHwordApp.so+0x163ce51`` value, but
static attribution proved that offset is an ASCII string table inside the RX
segment, not a return instruction.  Treating every mapped stack word as a
caller therefore produces false positives.

This pass runs the reviewed v4 generator and then follows only the canonical
x86-64 frame chain rooted at the syscall-time RBP.  Each frame must be aligned,
monotonically above the previous frame and remain within 64 KiB of the current
RSP.  At most eight ``[rbp]`` / ``[rbp+8]`` pairs are read.  Return addresses
are resolved through the existing executable-map table and emitted on a
separate bounded ``HRT M11 FRAMECTX`` line.

A writable, used byte array also preserves the exact artifact-selection marker
``HRT M11 FRAMECTX:`` in the linked Mach-O.  The runtime diagnostic literal may
otherwise be tail-merged with adjacent strings by the compiler, even though its
emitted log remains correct.  The array is never read by guest code and changes
no runtime behavior.

No arbitrary stack scan is credited as a caller, and all generated-source edits
remain exact and fail closed.
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
        "augment_hword_document_io_trace_v4.py"
    )
    if not generator.is_file():
        raise SystemExit(f"32-word open tracer not found: {generator}")

    with tempfile.TemporaryDirectory(prefix="hrt-m11-docio-v5-") as temporary:
        intermediate = Path(temporary) / "syscall_bridge_openctx32.c"
        subprocess.run(
            [sys.executable, str(generator), str(args.source), str(intermediate)],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M11 FRAMECTX:" in text:
        raise SystemExit("M11 frame-chain tracing is already present")

    text = replace_once(
        text,
        "#define M11_DOCIO_STACK_WORD_COUNT 32u\n",
        "#define M11_DOCIO_STACK_WORD_COUNT 32u\n"
        "#define M11_DOCIO_FRAME_COUNT 8u\n"
        "#define M11_DOCIO_FRAME_STACK_WINDOW UINT64_C(0x10000)\n"
        "#if defined(__clang__)\n"
        "__attribute__((used))\n"
        "#endif\n"
        "static volatile unsigned char m11_framectx_artifact_marker[] = {\n"
        "    0x48, 0x52, 0x54, 0x20, 0x4d, 0x31, 0x31, 0x20,\n"
        "    0x46, 0x52, 0x41, 0x4d, 0x45, 0x43, 0x54, 0x58,\n"
        "    0x3a, 0x00,\n"
        "};\n",
        "frame-chain constants and artifact marker",
    )

    text = replace_once(
        text,
        '''    uint64_t stack_words[M11_DOCIO_STACK_WORD_COUNT];
} M11OpenContext;
''',
        '''    uint64_t stack_words[M11_DOCIO_STACK_WORD_COUNT];
    uint64_t frame_pointer[M11_DOCIO_FRAME_COUNT];
    uint64_t frame_saved_pointer[M11_DOCIO_FRAME_COUNT];
    uint64_t frame_return_address[M11_DOCIO_FRAME_COUNT];
    unsigned int frame_count;
} M11OpenContext;
''',
        "frame-chain context fields",
    )

    capture_anchor = '''    for (unsigned int index = 0u;
         index < M11_DOCIO_STACK_WORD_COUNT; ++index) {
        context.stack_words[index] =
            m11_docio_stack_word(state->__rsp, index);
    }
    return context;
}
'''
    capture_replacement = '''    for (unsigned int index = 0u;
         index < M11_DOCIO_STACK_WORD_COUNT; ++index) {
        context.stack_words[index] =
            m11_docio_stack_word(state->__rsp, index);
    }

    const uint64_t stack_lower = state->__rsp;
    const uint64_t stack_upper =
        stack_lower <= UINT64_MAX - M11_DOCIO_FRAME_STACK_WINDOW
            ? stack_lower + M11_DOCIO_FRAME_STACK_WINDOW
            : UINT64_MAX;
    uint64_t frame = state->__rbp;
    while (context.frame_count < M11_DOCIO_FRAME_COUNT) {
        if ((frame & UINT64_C(7)) != 0u || frame < stack_lower ||
            frame > stack_upper || stack_upper - frame < UINT64_C(16)) {
            break;
        }
        const uint64_t saved =
            *(const uint64_t *)(uintptr_t)frame;
        const uint64_t returned =
            *(const uint64_t *)(uintptr_t)(frame + sizeof(uint64_t));
        const unsigned int index = context.frame_count++;
        context.frame_pointer[index] = frame;
        context.frame_saved_pointer[index] = saved;
        context.frame_return_address[index] = returned;
        if ((saved & UINT64_C(7)) != 0u || saved <= frame ||
            saved > stack_upper || stack_upper - saved < UINT64_C(16)) {
            break;
        }
        frame = saved;
    }
    return context;
}
'''
    text = replace_once(text, capture_anchor, capture_replacement,
                        "bounded frame-chain capture")

    emitter_anchor = '''    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static void m11_docio_note_open(int fd, const char *guest_path,
'''
    emitter_replacement = r'''    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static void m11_docio_emit_frame_context(
    const M11OpenContext *context) {
    const sig_atomic_t stage = g_m11_docio_stage;
    if (context == NULL || stage <= 0 || context->frame_count == 0u)
        return;

    char buffer[4096];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M11 FRAMECTX: stage=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  (uint64_t)(unsigned int)stage);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " syscall=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  context->syscall_number);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " count=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  context->frame_count);
    for (unsigned int index = 0u;
         index < context->frame_count && index < M11_DOCIO_FRAME_COUNT;
         ++index) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " frame");
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), index);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer), "-rbp=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  context->frame_pointer[index]);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " frame");
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), index);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      "-saved=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  context->frame_saved_pointer[index]);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      " frame");
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), index);
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                      "-return=");
        cursor = trace_append_hex(buffer, cursor, sizeof(buffer),
                                  context->frame_return_address[index]);

        char label[24];
        size_t label_cursor = 0u;
        label_cursor = trace_append_literal(
            label, label_cursor, sizeof(label), "frame");
        label_cursor = trace_append_decimal(
            label, label_cursor, sizeof(label), index);
        label_cursor = trace_append_literal(
            label, label_cursor, sizeof(label), "-return");
        if (label_cursor >= sizeof(label)) label_cursor = sizeof(label) - 1u;
        label[label_cursor] = '\0';
        cursor = m11_docio_append_resolution(
            buffer, cursor, sizeof(buffer), label,
            context->frame_return_address[index]);
    }
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static void m11_docio_note_open(int fd, const char *guest_path,
'''
    text = replace_once(text, emitter_anchor, emitter_replacement,
                        "frame-chain emitter insertion")

    text = replace_once(
        text,
        '''    m11_docio_emit_open_context(open_context);
}
''',
        '''    m11_docio_emit_open_context(open_context);
    m11_docio_emit_frame_context(open_context);
}
''',
        "frame-chain emission call",
    )

    required = {
        "HRT M11 FRAMECTX:": 1,
        "M11_DOCIO_FRAME_COUNT 8u": 1,
        "M11_DOCIO_FRAME_STACK_WINDOW UINT64_C(0x10000)": 1,
        "m11_framectx_artifact_marker": 1,
        "frame_return_address[M11_DOCIO_FRAME_COUNT]": 1,
        "context.frame_count++": 1,
        "m11_docio_emit_frame_context(": 2,
        "frame-return-object=": 0,
        "m11_docio_append_resolution(": 3,
        "M11_DOCIO_STACK_WORD_COUNT 32u": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"frame-chain marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
