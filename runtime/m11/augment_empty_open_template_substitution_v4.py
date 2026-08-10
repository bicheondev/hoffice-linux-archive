#!/usr/bin/env python3
"""Run the selectable empty-open probe on direct v8 attribution.

The reviewed substitution implementation is unchanged.  Its upstream tracer is
advanced from the historical v6 chain to ``augment_hword_document_io_trace_v8``
which directly composes OPENCTX, canonical FRAMECTX and validated CALLCTX on the
replay-proven v4 source.
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
        '        "augment_hword_document_io_trace_v8.py"\n',
        "direct v8 upstream tracer",
    )
    source = replace_once(
        source,
        "escaped frame-chain generator not found",
        "direct FRAMECTX/CALLCTX generator not found",
        "generator error label",
    )

    namespace = {
        "__name__": "hrt_m11_empty_open_direct_attribution",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched empty-open generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
