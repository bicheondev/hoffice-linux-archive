#!/usr/bin/env python3
"""Run the v3 open-callsite transform with literal C escapes and 16 stack words.

The reviewed v3 source used ordinary Python triple-quoted strings for the
``F_GETPATH`` source anchor and replacement.  The ``'\\0'`` spelling in those
strings is therefore interpreted by Python as an actual NUL byte, while the
generated C source contains the two printable characters ``\\`` and ``0``.
That representational mismatch made the otherwise exact anchor fail.

The first successful callsite replay also showed that glibc enters ``openat``
with ``RBP - RSP == 0x70``.  Its saved return slot is consequently stack word
15, beyond v3's original four-word diagnostic window.  Patch the two string
prefixes to raw literals and widen only that bounded window from four to
sixteen words before executing the unchanged v3 entry point.  Every generated-C
marker and fail-closed audit remains active.
"""
from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v3.py"
    )
    source = generator.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "    fgetpath_anchor = '''#ifdef F_GETPATH\n",
        "    fgetpath_anchor = r'''#ifdef F_GETPATH\n",
        "raw F_GETPATH anchor",
    )
    source = replace_once(
        source,
        "    fgetpath_replacement = '''#ifdef F_GETPATH\n",
        "    fgetpath_replacement = r'''#ifdef F_GETPATH\n",
        "raw F_GETPATH replacement",
    )
    source = replace_once(
        source,
        "#define M11_DOCIO_STACK_WORD_COUNT 4u",
        "#define M11_DOCIO_STACK_WORD_COUNT 16u",
        "sixteen-word generated C capture",
    )
    source = replace_once(
        source,
        '        "M11_DOCIO_STACK_WORD_COUNT 4u": 1,',
        '        "M11_DOCIO_STACK_WORD_COUNT 16u": 1,',
        "sixteen-word generated marker audit",
    )

    namespace = {
        "__name__": "hrt_m11_document_io_open_context_return_slot",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched open-callsite generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
