#!/usr/bin/env python3
"""Run the M11 document-I/O transform with brace-scoped C functions.

The mature filesystem composition inserts flock/link/chmod/statfs helpers
between ``host_write_bridge`` and ``host_close_bridge``.  The v1 generator used
the next named function as its range terminator, so a common libc-result tail
inside those inserted helpers made the write edit ambiguous.

Patch only the generator's function-range helper in memory.  The replacement
uses an opening brace already present in an exact one-line signature, otherwise
finds the first brace after a multiline signature, and then scans to the
matching close.  Every v1 anchor and marker audit remains intact.

The public v2 entry point then runs the reviewed open-callsite postprocessor
through the v7 classifier-caller wrapper.  v7 preserves v6's literal-safe
canonical frame chain and derives the direct caller of the exact
``libHwordApp.so+0xe15e32`` empty-path ``fopen`` from the statically verified
classifier frame layout.  The nested v2 invocation made by v3 is identified
both by an explicit environment guard and by v3's private temporary-directory
prefix, preventing recursion while preserving direct invocation of any entry
point.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def run_brace_scoped_v2() -> None:
    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace.py"
    )
    source = generator.read_text(encoding="utf-8")

    start = source.find("def replace_in_function(\n")
    end = source.find("\n\ndef main() -> None:\n", start)
    if start < 0 or end < 0:
        raise SystemExit("v1 function-range helper was not found")

    replacement = '''def replace_in_function(
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
    signature_brace = function_start.find("{")
    if signature_brace >= 0:
        opening = start + signature_brace
    else:
        opening = text.find("{", start + len(function_start))
    if opening < 0:
        raise SystemExit(f"{label}: opening function brace not found")

    depth = 0
    closing = -1
    for index in range(opening, len(text)):
        value = text[index]
        if value == "{":
            depth += 1
        elif value == "}":
            depth -= 1
            if depth == 0:
                closing = index + 1
                break
    if closing < 0:
        raise SystemExit(f"{label}: matching function brace not found")

    function = text[start:closing]
    count = function.count(needle)
    if count != 1:
        tail = function[-2400:].replace("\n", "\\n")
        raise SystemExit(
            f"{label}: expected one in-function anchor, found {count}; "
            f"function-tail={tail}")
    function = function.replace(needle, replacement, 1)

    # Retain the v1 call contract as an additional ordering invariant without
    # using the later function as the edit boundary.
    following = text.find(next_function_start, closing)
    if following < 0:
        raise SystemExit(f"{label}: later function invariant not found")
    return text[:start] + function + text[closing:]
'''
    patched = source[:start] + replacement + source[end:]

    namespace = {
        "__name__": "hrt_m11_document_io_trace_brace_scoped",
        "__file__": str(generator),
    }
    exec(compile(patched, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched document-I/O generator has no main entry")
    entry()


def should_run_open_context() -> bool:
    if os.environ.get("HRT_M11_DOCIO_V3_INNER") == "1":
        return False
    if len(sys.argv) != 3:
        return False
    output_parent = Path(sys.argv[2]).parent.name
    if output_parent.startswith("hrt-m11-docio-v3-"):
        return False
    return True


def run_open_context() -> None:
    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v7.py"
    )
    if not generator.is_file():
        raise SystemExit(
            f"open-callsite classifier-caller wrapper not found: {generator}")
    environment = os.environ.copy()
    environment["HRT_M11_DOCIO_V3_INNER"] = "1"
    subprocess.run(
        [sys.executable, str(generator), sys.argv[1], sys.argv[2]],
        check=True,
        env=environment,
    )


def main() -> None:
    run_brace_scoped_v2()
    if should_run_open_context():
        run_open_context()


if __name__ == "__main__":
    main()
