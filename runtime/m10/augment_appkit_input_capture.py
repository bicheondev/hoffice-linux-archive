#!/usr/bin/env python3
"""Run the audited M10 generator and enable it for the Korean HWord title.

The exact locale/resource-repaired HWord main window is titled ``한워드``.
The original audited staged-input generator selected only ``Word`` and thus
fell back to M8's generic one-shot center click.  Keep the original generator
materialized verbatim beside this wrapper, run it first, then make one exact,
fail-closed title-selection rewrite in the generated AppKit input source.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


BASE = Path(__file__).with_name("augment_appkit_input_capture_base.py")
INPUT_SOURCE = Path("runtime/m8/appkit_input.m")


def run_base() -> None:
    spec = importlib.util.spec_from_file_location(
        "hrt_m10_input_capture_base", BASE)
    if spec is None or spec.loader is None:
        raise SystemExit(f"unable to load {BASE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


def enable_korean_hword_title() -> None:
    text = INPUT_SOURCE.read_text(encoding="utf-8")
    replacement = (
        'if ([window.title isEqualToString:@"Word"] ||\n'
        '        [window.title isEqualToString:@"한워드"]) {'
    )
    if replacement in text:
        return

    original = 'if ([window.title isEqualToString:@"Word"]) {'
    count = text.count(original)
    if count != 1:
        raise SystemExit(
            f"Korean HWord title anchor: expected exactly one, found {count}")
    text = text.replace(original, replacement, 1)

    required = {
        'isEqualToString:@"한워드"': 1,
        'HRT M10 APPKIT: staged toolbar new-document click': 1,
        'HRT M10 APPKIT: staged document focus click': 1,
        'HRT M10 APPKIT: staged text input after focus': 1,
        'g_m10_synthetic_stage = 3u': 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"Korean staged-input marker {marker!r}: "
                f"expected {expected}, found {actual}")

    INPUT_SOURCE.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} SOURCE.m OUTPUT.m")
    run_base()
    enable_korean_hword_title()


if __name__ == "__main__":
    main()
