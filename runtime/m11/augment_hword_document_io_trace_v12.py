#!/usr/bin/env python3
"""Repair HWord's empty stack buffers with a bounded eight-byte HWDT alias.

A full absolute template path may exceed the small-string or stack buffer that
produced an empty ``fopen`` argument.  This safer experiment writes only the
8-byte NUL-terminated alias ``/d.hwdt`` into the original guest buffer, while
the current host open is redirected to the exact copied
``Document[0].hwdt``.  The alias preserves the HWDT extension without assuming
more than eight writable bytes.

The write is attempted for at most three stage-one, read-only,
``AT_FDCWD`` empty opens.  The path pointer must lie in the syscall thread's
64 KiB stack window and the eight target bytes must all be zero.  Every
candidate emits ``HRT M11 SHORTBUFFER`` with an applied or skip result.  v7's
canonical classifier and caller diagnostics remain unchanged, and no guest ELF
or on-disk product object is modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


def matching_brace(text: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(text)):
        value = text[index]
        if value == "{":
            depth += 1
        elif value == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    raise SystemExit("host_open_bridge: matching function brace not found")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v7.py"
    )
    if not generator.is_file():
        raise SystemExit(f"classifier-caller tracer not found: {generator}")

    with tempfile.TemporaryDirectory(prefix="hrt-m11-docio-v12-") as temporary:
        intermediate = Path(temporary) / "syscall_bridge_classifier.c"
        subprocess.run(
            [sys.executable, str(generator), str(args.source), str(intermediate)],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M11 SHORTBUFFER:" in text:
        raise SystemExit("stage-one short-buffer repair is already present")

    signature = "static int64_t host_open_bridge("
    count = text.count(signature)
    if count != 1:
        raise SystemExit(
            f"host_open_bridge: expected one signature, found {count}")
    start = text.index(signature)
    opening = text.find("{", start + len(signature))
    if opening < 0:
        raise SystemExit("host_open_bridge: opening function brace not found")
    closing = matching_brace(text, opening)
    function = text[start:closing]

    insertion = r'''
    static unsigned int m11_short_buffer_call_count;
    static const char m11_short_buffer_alias[] = "/d.hwdt";
    static const char m11_short_buffer_template[] =
        "/tmp/hrt-home/.hnc/User/Hword/Template/ko-KR/Document[0].hwdt";
    if (g_m11_docio_stage == 1 && directory_fd == LINUX_AT_FDCWD &&
        guest_path != NULL && guest_path[0] == '\0' &&
        (flags & UINT64_C(3)) == 0u &&
        m11_short_buffer_call_count < 3u) {
        const unsigned int index = ++m11_short_buffer_call_count;
        const uintptr_t pointer = (uintptr_t)guest_path;
        const uintptr_t stack_lower = open_context != NULL
            ? (uintptr_t)open_context->syscall_rsp : 0u;
        const uintptr_t stack_upper =
            stack_lower <= UINTPTR_MAX - UINT64_C(0x10000)
                ? stack_lower + UINT64_C(0x10000) : UINTPTR_MAX;
        const size_t alias_size = sizeof(m11_short_buffer_alias);
        int in_window = pointer >= stack_lower && pointer <= stack_upper &&
            stack_upper - pointer >= alias_size;
        int zero_region = in_window;
        if (zero_region) {
            const volatile unsigned char *probe =
                (const volatile unsigned char *)pointer;
            for (size_t offset = 0u; offset < alias_size; ++offset) {
                if (probe[offset] != 0u) {
                    zero_region = 0;
                    break;
                }
            }
        }
        if (in_window && zero_region) {
            volatile unsigned char *destination =
                (volatile unsigned char *)pointer;
            for (size_t offset = 0u; offset < alias_size; ++offset)
                destination[offset] =
                    (unsigned char)m11_short_buffer_alias[offset];
            if (index == 1u) {
                static const char marker[] =
                    "HRT M11 SHORTBUFFER: index=1 applied=1 alias=/d.hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            } else if (index == 2u) {
                static const char marker[] =
                    "HRT M11 SHORTBUFFER: index=2 applied=1 alias=/d.hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            } else {
                static const char marker[] =
                    "HRT M11 SHORTBUFFER: index=3 applied=1 alias=/d.hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            }
            guest_path = m11_short_buffer_template;
        } else if (!in_window) {
            static const char marker[] =
                "HRT M11 SHORTBUFFER: applied=0 reason=outside-stack-window\n";
            raw_write_literal(marker, sizeof(marker) - 1u);
        } else {
            static const char marker[] =
                "HRT M11 SHORTBUFFER: applied=0 reason=nonzero-eight-byte-region\n";
            raw_write_literal(marker, sizeof(marker) - 1u);
        }
    }
'''
    function = function[: function.index("{") + 1] + insertion + function[
        function.index("{") + 1 :]
    text = text[:start] + function + text[closing:]

    required = {
        "HRT M11 SHORTBUFFER:": 5,
        "m11_short_buffer_alias": 4,
        "m11_short_buffer_template": 2,
        '"/d.hwdt"': 1,
        "alias=/d.hwdt": 3,
        "m11_short_buffer_call_count < 3u": 1,
        "open_context->syscall_rsp": 1,
        "UINT64_C(0x10000)": 2,
        "reason=outside-stack-window": 1,
        "reason=nonzero-eight-byte-region": 1,
        "guest_path = m11_short_buffer_template;": 1,
        "HRT M11 CLASSIFIERCALLER:": 1,
        "HRT M11 FRAMECTX:": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"short-buffer marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
