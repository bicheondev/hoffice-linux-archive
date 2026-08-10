#!/usr/bin/env python3
"""Run the v5 frame-chain transform with literal C source anchors.

The frame emitter's reviewed replacement is already a raw Python string, but
its source anchor was ordinary triple-quoted text.  Python therefore converted
``'\\n'`` into a literal newline inside the character constant and the exact
generated-C anchor could not match.  Patch only that prefix to a raw string in
memory.

The v3 bridge already contains three ``m11_docio_append_resolution``
occurrences: the helper definition, syscall RIP resolution and arbitrary stack
resolution.  v5 adds one canonical frame-return resolution, making four.  Patch
only that generated-source audit count as well, then execute the unchanged v5
entry point with every other bound and marker check active.
"""
from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v5.py"
    )
    source = generator.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "    emitter_anchor = '''    if (cursor < sizeof(buffer))",
        "    emitter_anchor = r'''    if (cursor < sizeof(buffer))",
        "raw frame-emitter anchor",
    )
    source = replace_once(
        source,
        '        "m11_docio_append_resolution(": 3,',
        '        "m11_docio_append_resolution(": 4,',
        "frame-return resolver audit",
    )

    namespace = {
        "__name__": "hrt_m11_document_io_frame_chain_literal_newline",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched frame-chain generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
