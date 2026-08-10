#!/usr/bin/env python3
"""Run the v3 open-callsite transform with literal C NUL escapes.

The reviewed v3 source used ordinary Python triple-quoted strings for the
``F_GETPATH`` source anchor and replacement.  The ``'\\0'`` spelling in those
strings is therefore interpreted by Python as an actual NUL byte, while the
generated C source contains the two printable characters ``\\`` and ``0``.
That representational mismatch made the otherwise exact anchor fail.

Patch only those two Python string prefixes to raw triple-quoted strings in
memory, then execute the unchanged v3 entry point.  Every generated-C marker
and fail-closed audit in v3 remains active.
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

    namespace = {
        "__name__": "hrt_m11_document_io_open_context_literal_nul",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched open-callsite generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
