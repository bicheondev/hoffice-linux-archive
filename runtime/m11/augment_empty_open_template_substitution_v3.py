#!/usr/bin/env python3
"""Run the selectable empty-open probe on the CALLCTX-enabled tracer.

The empty-open implementation and all its fail-closed audits remain those of
``augment_empty_open_template_substitution_v2.py``.  Only the reviewed upstream
tracer is advanced from v6 to v7 so each A/B replay also records stack values
that are validated as real ``E8 rel32`` return addresses.
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
        "augment_empty_open_template_substitution_v2.py"
    )
    source = generator.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        "augment_hword_document_io_trace_v6.py"\n',
        '        "augment_hword_document_io_trace_v7.py"\n',
        "CALLCTX upstream tracer",
    )
    source = replace_once(
        source,
        "escaped frame-chain generator not found",
        "CALLCTX-enabled frame-chain generator not found",
        "generator error label",
    )

    namespace = {
        "__name__": "hrt_m11_empty_open_callctx_composition",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched empty-open generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
