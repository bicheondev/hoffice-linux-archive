#!/usr/bin/env python3
"""Run the v8 empty-path experiment with its exact counter audit.

The generated bridge contains five references to
``m11_empty_fallback_count``: the static declaration, upper bound, increment,
and the two explicit index branches.  Patch only that source-generator audit
from six to five before executing v8; all runtime bounds and every other marker
remain unchanged.
"""
from __future__ import annotations

from pathlib import Path


def main() -> None:
    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v8.py"
    )
    source = generator.read_text(encoding="utf-8")
    old = '        "m11_empty_fallback_count": 6,'
    new = '        "m11_empty_fallback_count": 5,'
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"empty-fallback counter audit: expected one anchor, found {count}")
    source = source.replace(old, new, 1)

    namespace = {
        "__name__": "hrt_m11_empty_fallback_exact_counter_audit",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched empty-fallback generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
