#!/usr/bin/env python3
"""Run the M11 native-key probe with its corrected fail-closed audit.

The first generator revision correctly emitted four ``HRT M11 KEYROUTE``
format strings, while its final invariant expected five.  It also used
``QScrollBar`` methods and therefore needs the concrete QtWidgets header rather
than the forward declaration inherited through QAbstractScrollArea.

Keep the reviewed v1 transform intact, patch exactly those two generator facts
in memory, then invoke its normal entry point with the original arguments.
"""
from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one generator anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    generator = Path(__file__).with_name("augment_qpa_native_key_probe.py")
    source = generator.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "        '#include <QtCore/qthread.h>\\n'\n    )",
        "        '#include <QtCore/qthread.h>\\n'\n"
        "        '#include <QtWidgets/qscrollbar.h>\\n'\n"
        "    )",
        "QScrollBar concrete include",
    )
    source = replace_once(
        source,
        '        "HRT M11 KEYROUTE:": 5,',
        '        "HRT M11 KEYROUTE:": 4,',
        "native key-route marker count",
    )

    namespace = {
        "__name__": "hrt_m11_native_key_probe_v1",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched native-key generator has no main entry point")
    entry()


if __name__ == "__main__":
    main()
