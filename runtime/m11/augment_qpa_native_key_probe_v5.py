#!/usr/bin/env python3
"""Compile the credible-editor native-key probe in dependency order.

The reviewed v3 transform defines ``m11FindCredibleEditorWidget`` after the
materialization helper, while that helper now calls it.  C++ therefore requires
forward declarations before ``m11LogMaterializationState``.  Patch the Python
generator in memory to emit those declarations, correct the one generator-only
path invariant, and invoke the unchanged v3 entry point.

The declarations raise the generated marker counts to the original v3 values
(7 credible-receiver occurrences and 4 editor-finder occurrences), so unlike
v4 this wrapper does not weaken those audits.
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

    insertion_anchor = (
        "    text = replace_once(text, helper_anchor, helpers,\n"
        "                        \"credible editor helper insertion\")\n\n"
        "    timeout_anchor = '''"
    )
    insertion_replacement = (
        "    text = replace_once(text, helper_anchor, helpers,\n"
        "                        \"credible editor helper insertion\")\n\n"
        "    declaration_anchor = '''static void "
        "m11LogMaterializationState(QWidget *topLevel,\n"
        "'''\n"
        "    declaration_replacement = '''static bool "
        "m11CredibleTextReceiver(QObject *receiver);\n"
        "static QWidget *m11FindCredibleEditorWidget(QWidget *topLevel);\n\n"
        "static void m11LogMaterializationState(QWidget *topLevel,\n"
        "'''\n"
        "    text = replace_once(text, declaration_anchor, "
        "declaration_replacement,\n"
        "                        \"credible editor forward declarations\")\n\n"
        "    timeout_anchor = '''"
    )
    source = replace_once(
        source,
        insertion_anchor,
        insertion_replacement,
        "forward-declaration transform insertion",
    )
    source = replace_once(
        source,
        '        "augment_qpa_native_key_probe_v2.py": 1,',
        '        "augment_qpa_native_key_probe_v2.py": 0,',
        "generator-only path marker",
    )

    namespace = {
        "__name__": "hrt_m11_native_key_probe_v3_ordered",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("ordered credible-editor generator has no main")
    entry()


if __name__ == "__main__":
    main()
