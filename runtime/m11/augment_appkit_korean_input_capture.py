#!/usr/bin/env python3
"""Extend the proven M10 staged-input adapter to Korean HWord and dialogs.

The locked M10 generator deliberately selected only an AppKit window titled
``Word``.  Once the locale and resource repair became exact, the same real
800×600 editor window is titled ``한워드``; it consequently fell through to
the old one-shot M8 click-and-key sequence and never clicked the New toolbar
button.

After preserving that exact title rewrite, this wrapper arms the bounded HWord
document-I/O trace immediately before each staged input action and applies the
M11 multi-window transform.  The full product payload creates a real Qt dialog
on the New-document path, and the adapter must retain the main NSWindow while
materializing that secondary surface.  All transforms remain separate and fail
closed, including an explicit audit that generated Objective-C log strings
retain literal ``\\n`` escapes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def run_m10_generator(source: Path, output: Path) -> None:
    generator = Path(__file__).resolve().parents[1] / "m10" / \
        "augment_appkit_input_capture.py"
    spec = importlib.util.spec_from_file_location(
        "hrt_m11_m10_input_generator", generator)
    if spec is None or spec.loader is None:
        raise SystemExit(f"unable to load {generator}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = sys.argv
    try:
        sys.argv = [str(generator), str(source), str(output)]
        module.main()
    finally:
        sys.argv = previous


def allow_korean_title(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    korean = (
        'if ([window.title isEqualToString:@"Word"] ||\n'
        '        [window.title isEqualToString:@"한워드"]) {'
    )
    if korean in text:
        return
    original = 'if ([window.title isEqualToString:@"Word"]) {'
    count = text.count(original)
    if count != 1:
        raise SystemExit(
            f"Korean HWord title anchor: expected one, found {count}")
    text = text.replace(original, korean, 1)

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
    path.write_text(text, encoding="utf-8")


def arm_document_io_stages(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "hrt_m11_docio_mark_stage" in text:
        raise SystemExit("document-I/O stage markers are already present")

    text = replace_once(
        text,
        "#include <string.h>\n",
        "#include <string.h>\n\n"
        "extern void hrt_m11_docio_mark_stage(unsigned int stage);\n",
        "document-I/O stage declaration",
    )
    for stage, label in (
        (0, "toolbar document-I/O stage"),
        (1, "document-focus I/O stage"),
        (2, "text-input I/O stage"),
    ):
        guard = f"        if (g_m10_synthetic_stage == {stage}u) {{\n"
        replacement = (
            guard
            + f"            hrt_m11_docio_mark_stage({stage + 1}u);\n"
        )
        text = replace_once(text, guard, replacement, label)

    required = {
        "extern void hrt_m11_docio_mark_stage": 1,
        "hrt_m11_docio_mark_stage(1u);": 1,
        "hrt_m11_docio_mark_stage(2u);": 1,
        "hrt_m11_docio_mark_stage(3u);": 1,
        "HRT M10 APPKIT: staged toolbar new-document click": 1,
        "HRT M10 APPKIT: staged document focus click": 1,
        "HRT M10 APPKIT: staged text input after focus": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"document-I/O input marker {marker!r}: "
                f"expected {expected}, found {actual}")
    path.write_text(text, encoding="utf-8")


def apply_multiwindow_adapter(path: Path) -> None:
    generator = Path(__file__).with_name("augment_appkit_multiwindow_v2.py")
    if not generator.is_file():
        raise SystemExit(f"multi-window adapter generator not found: {generator}")

    source_text = path.read_text(encoding="utf-8")
    marker = "hrt_m8_input_attach"
    position = source_text.find(marker)
    if position < 0:
        raise SystemExit("generated adapter has no hrt_m8_input_attach call")

    with tempfile.TemporaryDirectory(prefix="hrt-m11-appkit-windows-") as temp:
        generated = Path(temp) / "appkit_adapter_multiwindow.m"
        subprocess.run(
            [sys.executable, str(generator), str(path), str(generated)],
            check=True,
        )
        text = generated.read_text(encoding="utf-8")
        required = {
            "HRT M11 APPKIT: registered native window": 1,
            "HRT M11 APPKIT: modal first-frame capture": 1,
            "HRT_M11_MODAL_CAPTURE_PATH": 2,
            "m11_select_window_number(": 5,
            'input-window=%ld\\n",': 1,
        }
        for marker, expected in required.items():
            actual = text.count(marker)
            if actual != expected:
                raise SystemExit(
                    f"multi-window output marker {marker!r}: "
                    f"expected {expected}, found {actual}")
        path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} SOURCE.m OUTPUT.m")
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    input_source = Path("runtime/m8/appkit_input.m")
    run_m10_generator(source, output)
    allow_korean_title(input_source)
    arm_document_io_stages(input_source)
    apply_multiwindow_adapter(output)


if __name__ == "__main__":
    main()
