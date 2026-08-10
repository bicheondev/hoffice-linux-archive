#!/usr/bin/env python3
"""Test whether HWord's three empty stage-one opens require the active HWDT.

The exact blank-document replay proves that ``Document[0].hwdt`` is copied in
full and its ZIP/XML payload is valid.  Immediately afterwards HWord performs
three read-only ``openat(AT_FDCWD, "", ...)`` operations and presents its data
validation dialog.  Earlier arbitrary stack attribution was rejected; the
reviewed v7 transform preserves the canonical classifier/caller diagnostics.

This pass runs v7 unchanged, then adds one deliberately narrow and reversible
experiment at the host ``open`` boundary.  During document stage 1 only, at
most three read-only empty-path requests using ``AT_FDCWD`` are redirected to
the exact copied template:

``/tmp/hrt-home/.hnc/User/Hword/Template/ko-KR/Document[0].hwdt``

Every substitution emits a fixed ``HRT M11 EMPTYFALLBACK`` marker.  Non-empty
paths, later stages, writes, other directory descriptors and calls after the
third substitution retain their original behavior.  No guest ELF is modified
by this transform.
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

    with tempfile.TemporaryDirectory(prefix="hrt-m11-docio-v8-") as temporary:
        intermediate = Path(temporary) / "syscall_bridge_classifier.c"
        subprocess.run(
            [sys.executable, str(generator), str(args.source), str(intermediate)],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M11 EMPTYFALLBACK:" in text:
        raise SystemExit("stage-one empty-path fallback is already present")

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
    static unsigned int m11_empty_fallback_count;
    static const char m11_blank_template[] =
        "/tmp/hrt-home/.hnc/User/Hword/Template/ko-KR/Document[0].hwdt";
    if (g_m11_docio_stage == 1 && directory_fd == LINUX_AT_FDCWD &&
        guest_path != NULL && guest_path[0] == '\0' &&
        (flags & UINT64_C(3)) == 0u &&
        m11_empty_fallback_count < 3u) {
        ++m11_empty_fallback_count;
        if (m11_empty_fallback_count == 1u) {
            static const char marker[] =
                "HRT M11 EMPTYFALLBACK: index=1 replacement=Document[0].hwdt\n";
            raw_write_literal(marker, sizeof(marker) - 1u);
        } else if (m11_empty_fallback_count == 2u) {
            static const char marker[] =
                "HRT M11 EMPTYFALLBACK: index=2 replacement=Document[0].hwdt\n";
            raw_write_literal(marker, sizeof(marker) - 1u);
        } else {
            static const char marker[] =
                "HRT M11 EMPTYFALLBACK: index=3 replacement=Document[0].hwdt\n";
            raw_write_literal(marker, sizeof(marker) - 1u);
        }
        guest_path = m11_blank_template;
    }
'''
    function = function[: function.index("{") + 1] + insertion + function[
        function.index("{") + 1 :]
    text = text[:start] + function + text[closing:]

    required = {
        "HRT M11 EMPTYFALLBACK:": 3,
        "m11_empty_fallback_count": 6,
        "m11_blank_template": 2,
        "Document[0].hwdt": 4,
        "g_m11_docio_stage == 1": 1,
        "directory_fd == LINUX_AT_FDCWD": 1,
        "guest_path[0] == '\\0'": 1,
        "m11_empty_fallback_count < 3u": 1,
        "guest_path = m11_blank_template;": 1,
        "HRT M11 CLASSIFIERCALLER:": 1,
        "HRT M11 FRAMECTX:": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"empty-path fallback marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
