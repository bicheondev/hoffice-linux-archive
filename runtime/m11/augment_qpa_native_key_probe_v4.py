#!/usr/bin/env python3
"""Run the credible-editor native-key generator with corrected invariants.

The reviewed v3 transform emits six calls/definitions containing
``m11CredibleTextReceiver`` and three containing
``m11FindCredibleEditorWidget``.  Its script-path audit belongs to the Python
generator, not the generated C++ source.  Patch only those fail-closed counts
in memory and invoke the unchanged v3 entry point.
"""
from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one generator anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    generator = Path(__file__).with_name(
        "augment_qpa_native_key_probe_v3.py"
    )
    source = generator.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        "m11CredibleTextReceiver(": 7,',
        '        "m11CredibleTextReceiver(": 6,',
        "credible receiver marker count",
    )
    source = replace_once(
        source,
        '        "m11FindCredibleEditorWidget(": 4,',
        '        "m11FindCredibleEditorWidget(": 3,',
        "credible editor finder marker count",
    )
    source = replace_once(
        source,
        '        "augment_qpa_native_key_probe_v2.py": 1,',
        '        "augment_qpa_native_key_probe_v2.py": 0,',
        "generator-only path marker",
    )

    namespace = {
        "__name__": "hrt_m11_native_key_probe_v3",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched credible-editor generator has no main")
    entry()


if __name__ == "__main__":
    main()
