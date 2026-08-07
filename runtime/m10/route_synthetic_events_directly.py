#!/usr/bin/env python3
"""Route only M10's staged synthetic NSEvents directly into the monitor.

A posted NSEvent can be observed by the local AppKit monitor one event at a
time across several Qt flushes.  That allowed the next M10 stage to be posted
before the preceding mouse-up had reached HWord, so the text key arrived before
focus was established.  Real user events still enter through the installed
local monitor.  This deterministic test-only rewrite feeds the already-created
NSEvent objects through that exact monitor synchronously, preserving strict
stage order while retaining the full AppKit→opcode-262→Qt conversion path.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M10 APPKIT: synchronous staged event capture" in text:
        raise SystemExit("M10 synchronous staged capture is already present")

    for variable, label in (
        ("new_document", "new-document stage"),
        ("focus_input", "focus stage"),
        ("text_input", "text stage"),
    ):
        old = (
            f"            for (NSEvent *event in {variable})\n"
            "                [NSApp postEvent:event atStart:NO];\n"
        )
        new = (
            f"            for (NSEvent *event in {variable})\n"
            "                (void)monitor_event(event);\n"
        )
        text = replace_once(text, old, new, label)

    marker_anchor = (
        "            g_m10_synthetic_stage = 1u;\n"
        "            fprintf(stderr,\n"
        "                    \"HRT M10 APPKIT: staged toolbar new-document click window=%ld point=%.0f,%.0f\\\\n\",\n"
    )
    marker_replacement = (
        "            g_m10_synthetic_stage = 1u;\n"
        "            fprintf(stderr,\n"
        "                    \"HRT M10 APPKIT: synchronous staged event capture stage=new-document count=3\\\\n\");\n"
        "            fprintf(stderr,\n"
        "                    \"HRT M10 APPKIT: staged toolbar new-document click window=%ld point=%.0f,%.0f\\\\n\",\n"
    )
    text = replace_once(
        text, marker_anchor, marker_replacement,
        "synchronous staged-event marker",
    )

    required = {
        "(void)monitor_event(event);": 3,
        "[NSApp postEvent:event atStart:NO];": 1,
        "HRT M10 APPKIT: synchronous staged event capture": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"post-rewrite marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.source.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
