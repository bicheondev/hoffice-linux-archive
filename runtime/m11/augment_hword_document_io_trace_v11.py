#!/usr/bin/env python3
"""Test a bounded guest-stack repair for HWord's empty document paths.

Host-only redirection changes which file Darwin opens but leaves HWord's own
path buffer empty.  If the classifier or loader consults that buffer after
``fopen`` returns, the host-only experiment cannot repair the state transition.

This transform preserves the reviewed v7 caller diagnostics and, for at most
three stage-one read-only empty opens, writes the exact copied HWDT path into
the original guest buffer before normal path translation.  The write is
allowed only when all of the following hold:

* the path pointer lies at or above the syscall-time RSP;
* the complete replacement stays within a 64 KiB stack window;
* the first replacement-sized region is entirely zero; and
* the call uses ``AT_FDCWD`` with read-only access.

Every candidate emits ``HRT M11 EMPTYBUFFER`` with ``applied=1`` or a bounded
skip reason.  This is a reversible diagnostic memory experiment; no guest ELF
or on-disk document is modified.
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

    with tempfile.TemporaryDirectory(prefix="hrt-m11-docio-v11-") as temporary:
        intermediate = Path(temporary) / "syscall_bridge_classifier.c"
        subprocess.run(
            [sys.executable, str(generator), str(args.source), str(intermediate)],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M11 EMPTYBUFFER:" in text:
        raise SystemExit("stage-one guest-buffer repair is already present")

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
    static unsigned int m11_empty_buffer_call_count;
    static const char m11_empty_buffer_template[] =
        "/tmp/hrt-home/.hnc/User/Hword/Template/ko-KR/Document[0].hwdt";
    if (g_m11_docio_stage == 1 && directory_fd == LINUX_AT_FDCWD &&
        guest_path != NULL && guest_path[0] == '\0' &&
        (flags & UINT64_C(3)) == 0u &&
        m11_empty_buffer_call_count < 3u) {
        const unsigned int index = ++m11_empty_buffer_call_count;
        const uintptr_t pointer = (uintptr_t)guest_path;
        const uintptr_t stack_lower = open_context != NULL
            ? (uintptr_t)open_context->syscall_rsp : 0u;
        const uintptr_t stack_upper =
            stack_lower <= UINTPTR_MAX - UINT64_C(0x10000)
                ? stack_lower + UINT64_C(0x10000) : UINTPTR_MAX;
        int in_window = pointer >= stack_lower && pointer <= stack_upper &&
            stack_upper - pointer >= sizeof(m11_empty_buffer_template);
        int zero_region = in_window;
        if (zero_region) {
            const volatile unsigned char *probe =
                (const volatile unsigned char *)pointer;
            for (size_t offset = 0u;
                 offset < sizeof(m11_empty_buffer_template); ++offset) {
                if (probe[offset] != 0u) {
                    zero_region = 0;
                    break;
                }
            }
        }
        if (in_window && zero_region) {
            volatile unsigned char *destination =
                (volatile unsigned char *)pointer;
            for (size_t offset = 0u;
                 offset < sizeof(m11_empty_buffer_template); ++offset) {
                destination[offset] =
                    (unsigned char)m11_empty_buffer_template[offset];
            }
            if (index == 1u) {
                static const char marker[] =
                    "HRT M11 EMPTYBUFFER: index=1 applied=1 replacement=Document[0].hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            } else if (index == 2u) {
                static const char marker[] =
                    "HRT M11 EMPTYBUFFER: index=2 applied=1 replacement=Document[0].hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            } else {
                static const char marker[] =
                    "HRT M11 EMPTYBUFFER: index=3 applied=1 replacement=Document[0].hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            }
        } else if (!in_window) {
            static const char marker[] =
                "HRT M11 EMPTYBUFFER: applied=0 reason=outside-stack-window\n";
            raw_write_literal(marker, sizeof(marker) - 1u);
        } else {
            static const char marker[] =
                "HRT M11 EMPTYBUFFER: applied=0 reason=nonzero-region\n";
            raw_write_literal(marker, sizeof(marker) - 1u);
        }
    }
'''
    function = function[: function.index("{") + 1] + insertion + function[
        function.index("{") + 1 :]
    text = text[:start] + function + text[closing:]

    required = {
        "HRT M11 EMPTYBUFFER:": 5,
        "m11_empty_buffer_template": 5,
        "m11_empty_buffer_call_count < 3u": 1,
        "open_context->syscall_rsp": 1,
        "UINT64_C(0x10000)": 2,
        "replacement=Document[0].hwdt": 3,
        "reason=outside-stack-window": 1,
        "reason=nonzero-region": 1,
        "destination[offset] =": 1,
        "HRT M11 CLASSIFIERCALLER:": 1,
        "HRT M11 FRAMECTX:": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"empty-buffer marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
