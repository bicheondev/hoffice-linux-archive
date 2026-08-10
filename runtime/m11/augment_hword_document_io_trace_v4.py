#!/usr/bin/env python3
"""Run the v3 open-callsite transform with literal C escapes and 32 stack words.

The reviewed v3 source used ordinary Python triple-quoted strings for the
``F_GETPATH`` source anchor and replacement.  The ``'\\0'`` spelling in those
strings is therefore interpreted by Python as an actual NUL byte, while the
generated C source contains the two printable characters ``\\`` and ``0``.
That representational mismatch made the otherwise exact anchor fail.

The saved-return replay showed two nested glibc frames.  At the Linux syscall
boundary ``RBP - RSP == 0x70``; stack word 15 is the return into libc at file
offset ``0x91b0f``.  That caller's saved frame pointer is itself at stack word
20, making its return to the HWord-side caller stack word 21.  Widen the bounded
capture to 32 words so both libc frames and the first non-libc return are
resolved without walking arbitrary memory.  Every generated-C marker and
fail-closed audit remains active.
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
        "#define M11_DOCIO_STACK_WORD_COUNT 32u",
        "thirty-two-word generated C capture",
    )
    source = replace_once(
        source,
        '        "M11_DOCIO_STACK_WORD_COUNT 4u": 1,',
        '        "M11_DOCIO_STACK_WORD_COUNT 32u": 1,',
        "thirty-two-word generated marker audit",
    )

    namespace = {
        "__name__": "hrt_m11_document_io_open_context_hword_return",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched open-callsite generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
