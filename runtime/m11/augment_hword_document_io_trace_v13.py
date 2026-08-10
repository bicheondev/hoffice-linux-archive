#!/usr/bin/env python3
"""Run the short-buffer experiment with its exact alias-reference audit.

The generated bridge references ``m11_short_buffer_alias`` three times: its
static declaration, ``sizeof`` bound and byte-copy source.  Patch only v12's
source-generator audit from four to three before executing it.  The eight-byte
write bound, three-call limit and all runtime diagnostics remain unchanged.
"""
from __future__ import annotations

from pathlib import Path


def main() -> None:
    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v12.py"
    )
    source = generator.read_text(encoding="utf-8")
    old = '        "m11_short_buffer_alias": 4,'
    new = '        "m11_short_buffer_alias": 3,'
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"short-buffer alias audit: expected one anchor, found {count}")
    source = source.replace(old, new, 1)

    namespace = {
        "__name__": "hrt_m11_short_buffer_exact_alias_audit",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched short-buffer generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
