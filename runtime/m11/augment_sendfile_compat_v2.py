#!/usr/bin/env python3
"""Run the reviewed sendfile transform with generated-source-specific audits.

The v1 implementation is unchanged.  Its first audit counted globally common
host-context helper calls after many earlier transforms had already introduced
them, and counted two value-bearing macro definitions where only one exists.
Patch only those audit entries in memory, retaining every source anchor and the
sendfile implementation itself.
"""
from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one audit anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    generator = Path(__file__).with_name("augment_sendfile_compat_v1.py")
    source = generator.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        "M11_SENDFILE_BUFFER_BYTES 16384u": 2,\n',
        '        "M11_SENDFILE_BUFFER_BYTES 16384u": 1,\n',
        "buffer macro audit",
    )
    source = replace_once(
        source,
        '        "M11_SENDFILE_TRACE_LIMIT 32u": 2,\n',
        '        "M11_SENDFILE_TRACE_LIMIT 32u": 1,\n',
        "trace macro audit",
    )
    source = replace_once(
        source,
        '        "lseek(input_fd": 1,\n',
        '        "lseek(input_fd": 2,\n',
        "input-position audit",
    )
    source = replace_once(
        source,
        '        "switch_to_host_context()": 4,\n'
        '        "restore_guest_context(guest_context);": 4,\n',
        '',
        "global host-context audit removal",
    )

    namespace = {
        "__name__": "hrt_m11_sendfile_compat_generated_audit",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched sendfile generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
