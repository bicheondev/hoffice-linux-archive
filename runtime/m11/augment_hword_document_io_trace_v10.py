#!/usr/bin/env python3
"""Add a compile-time mask for HWord's first three stage-one empty opens.

The all-three HWDT substitution is useful as a closure experiment but cannot
show whether one classifier probe needs the active document while another
intentionally expects failure.  This transform keeps the reviewed v7 caller
and frame diagnostics and makes each of the first three read-only empty
``openat(AT_FDCWD, ...)`` boundaries independently selectable with
``HRT_M11_EMPTY_FALLBACK_MASK``.

Bit 0 controls the first qualifying call, bit 1 the second and bit 2 the third.
The default is ``7``.  Every qualifying call emits a fixed ``HRT M11 EMPTYMASK``
line recording its ordinal and whether substitution was applied.  Applied
calls receive the exact copied ``Document[0].hwdt`` path; skipped calls preserve
the original empty path and result.  No guest ELF is modified.
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

    with tempfile.TemporaryDirectory(prefix="hrt-m11-docio-v10-") as temporary:
        intermediate = Path(temporary) / "syscall_bridge_classifier.c"
        subprocess.run(
            [sys.executable, str(generator), str(args.source), str(intermediate)],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M11 EMPTYMASK:" in text:
        raise SystemExit("stage-one empty-path mask is already present")

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
#ifndef HRT_M11_EMPTY_FALLBACK_MASK
#define HRT_M11_EMPTY_FALLBACK_MASK 7u
#endif
    static unsigned int m11_empty_mask_call_count;
    static const char m11_empty_mask_template[] =
        "/tmp/hrt-home/.hnc/User/Hword/Template/ko-KR/Document[0].hwdt";
    if (g_m11_docio_stage == 1 && directory_fd == LINUX_AT_FDCWD &&
        guest_path != NULL && guest_path[0] == '\0' &&
        (flags & UINT64_C(3)) == 0u &&
        m11_empty_mask_call_count < 3u) {
        const unsigned int index = ++m11_empty_mask_call_count;
        const unsigned int bit = 1u << (index - 1u);
        const int applied =
            (HRT_M11_EMPTY_FALLBACK_MASK & bit) != 0u;
        if (index == 1u) {
            if (applied) {
                static const char marker[] =
                    "HRT M11 EMPTYMASK: index=1 applied=1 target=Document[0].hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            } else {
                static const char marker[] =
                    "HRT M11 EMPTYMASK: index=1 applied=0 target=original-empty\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            }
        } else if (index == 2u) {
            if (applied) {
                static const char marker[] =
                    "HRT M11 EMPTYMASK: index=2 applied=1 target=Document[0].hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            } else {
                static const char marker[] =
                    "HRT M11 EMPTYMASK: index=2 applied=0 target=original-empty\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            }
        } else {
            if (applied) {
                static const char marker[] =
                    "HRT M11 EMPTYMASK: index=3 applied=1 target=Document[0].hwdt\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            } else {
                static const char marker[] =
                    "HRT M11 EMPTYMASK: index=3 applied=0 target=original-empty\n";
                raw_write_literal(marker, sizeof(marker) - 1u);
            }
        }
        if (applied)
            guest_path = m11_empty_mask_template;
    }
'''
    function = function[: function.index("{") + 1] + insertion + function[
        function.index("{") + 1 :]
    text = text[:start] + function + text[closing:]

    required = {
        "HRT M11 EMPTYMASK:": 6,
        "HRT_M11_EMPTY_FALLBACK_MASK": 3,
        "m11_empty_mask_template": 2,
        "Document[0].hwdt": 4,
        "target=original-empty": 3,
        "g_m11_docio_stage == 1": 1,
        "directory_fd == LINUX_AT_FDCWD": 1,
        "guest_path[0] == '\\0'": 1,
        "m11_empty_mask_call_count < 3u": 1,
        "guest_path = m11_empty_mask_template;": 1,
        "HRT M11 CLASSIFIERCALLER:": 1,
        "HRT M11 FRAMECTX:": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"empty-path mask marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
