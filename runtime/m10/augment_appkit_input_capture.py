#!/usr/bin/env python3
"""Generate a frame-separated HWord toolbar, focus, and text sequence.

The real culture-repaired HWord window starts with no open document.  A
Ctrl+N event reaches the exact Qt window but is not accepted by this Linux
build's shortcut path.  The toolbar's enabled blank-document button is part of
the rendered HWord UI, so this generator drives that real control instead:

1. frame 1: click the blank-document toolbar button;
2. frame 2: click inside the document canvas;
3. frame 3: capture the focused baseline, then type ``a``;
4. frame 5: capture after two repaint opportunities.

The toolbar point is expressed in AppKit's bottom-left window coordinates.  It
maps to approximately ``(27, 163)`` in the 800x600 Qt content surface, matching
the blank-document icon observed in the durable M9 HWord frame.  All source
rewrites remain exact-anchor and fail closed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "058b66e4f65572abddc38b59398ddedf52380be6"
LOCKED_PATH = "runtime/m10/augment_appkit_input_capture.py"


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def run_locked_generator() -> None:
    source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="hrt-m10-input-") as temporary:
        module_path = Path(temporary) / "locked_m10_generator.py"
        module_path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m10_locked_generator", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked M10 generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main()


def replace_new_document_shortcut(text: str) -> str:
    old = r'''        if (g_m10_synthetic_stage == 0u) {
            NSArray<NSEvent *> *new_document = @[
                m10_synthetic_key(NSEventTypeKeyDown, window, @"n",
                    NSEventModifierFlagControl, 45),
                m10_synthetic_key(NSEventTypeKeyUp, window, @"n",
                    NSEventModifierFlagControl, 45),
            ];
            for (NSEvent *event in new_document)
                [NSApp postEvent:event atStart:NO];
            g_m10_synthetic_stage = 1u;
            fprintf(stderr,
                    "HRT M10 APPKIT: staged Ctrl+N new-document input window=%ld\n",
                    (long)window.windowNumber);
            fflush(stderr);
            return;
        }
'''
    new = r'''        if (g_m10_synthetic_stage == 0u) {
            const NSRect bounds = window.contentView != nil
                ? window.contentView.bounds
                : NSMakeRect(0.0, 0.0, 800.0, 600.0);
            /*
             * The durable 800x600 HWord frame places the enabled blank-page
             * toolbar icon at Qt-local x=27, y=163.  NSEvent window positions
             * use a bottom-left origin, so invert only the Y coordinate here.
             */
            const NSPoint point = NSMakePoint(
                NSMinX(bounds) + 27.0,
                NSMaxY(bounds) - 163.0);
            NSArray<NSEvent *> *new_document = @[
                synthetic_mouse(NSEventTypeMouseMoved, window, point, 8091),
                synthetic_mouse(NSEventTypeLeftMouseDown, window, point, 8092),
                synthetic_mouse(NSEventTypeLeftMouseUp, window, point, 8093),
            ];
            for (NSEvent *event in new_document)
                [NSApp postEvent:event atStart:NO];
            g_m10_synthetic_stage = 1u;
            fprintf(stderr,
                    "HRT M10 APPKIT: staged toolbar new-document click window=%ld point=%.0f,%.0f\n",
                    (long)window.windowNumber, point.x, point.y);
            fflush(stderr);
            return;
        }
'''
    return replace_once(text, old, new, "toolbar new-document stage")


def split_input_stages(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_new_document_shortcut(text)

    old = r'''        if (g_m10_synthetic_stage == 1u) {
            const NSRect bounds = window.contentView != nil
                ? window.contentView.bounds
                : NSMakeRect(0.0, 0.0, 800.0, 600.0);
            /* Aim below the ribbon and inside the document canvas. */
            const NSPoint point = NSMakePoint(
                NSMidX(bounds), NSMinY(bounds) + NSHeight(bounds) * 0.58);
            NSArray<NSEvent *> *document_input = @[
                synthetic_mouse(NSEventTypeMouseMoved, window, point, 8101),
                synthetic_mouse(NSEventTypeLeftMouseDown, window, point, 8102),
                synthetic_mouse(NSEventTypeLeftMouseUp, window, point, 8103),
                synthetic_key(NSEventTypeKeyDown, window),
                synthetic_key(NSEventTypeKeyUp, window),
            ];
            for (NSEvent *event in document_input)
                [NSApp postEvent:event atStart:NO];
            g_m10_synthetic_stage = 2u;
            g_synthetic_input_injected = YES;
            fprintf(stderr,
                    "HRT M10 APPKIT: staged document click and text input window=%ld point=%.0f,%.0f\n",
                    (long)window.windowNumber, point.x, point.y);
            fflush(stderr);
            return;
        }
        return;
'''
    new = r'''        if (g_m10_synthetic_stage == 1u) {
            const NSRect bounds = window.contentView != nil
                ? window.contentView.bounds
                : NSMakeRect(0.0, 0.0, 800.0, 600.0);
            /* Aim below the ribbon and inside the document canvas. */
            const NSPoint point = NSMakePoint(
                NSMidX(bounds), NSMinY(bounds) + NSHeight(bounds) * 0.58);
            NSArray<NSEvent *> *focus_input = @[
                synthetic_mouse(NSEventTypeMouseMoved, window, point, 8101),
                synthetic_mouse(NSEventTypeLeftMouseDown, window, point, 8102),
                synthetic_mouse(NSEventTypeLeftMouseUp, window, point, 8103),
            ];
            for (NSEvent *event in focus_input)
                [NSApp postEvent:event atStart:NO];
            g_m10_synthetic_stage = 2u;
            fprintf(stderr,
                    "HRT M10 APPKIT: staged document focus click window=%ld point=%.0f,%.0f\n",
                    (long)window.windowNumber, point.x, point.y);
            fflush(stderr);
            return;
        }

        if (g_m10_synthetic_stage == 2u) {
            NSArray<NSEvent *> *text_input = @[
                synthetic_key(NSEventTypeKeyDown, window),
                synthetic_key(NSEventTypeKeyUp, window),
            ];
            for (NSEvent *event in text_input)
                [NSApp postEvent:event atStart:NO];
            g_m10_synthetic_stage = 3u;
            g_synthetic_input_injected = YES;
            fprintf(stderr,
                    "HRT M10 APPKIT: staged text input after focus window=%ld\n",
                    (long)window.windowNumber);
            fprintf(stderr,
                    "HRT M8 APPKIT: posted deterministic focus click, key and mouse events\n");
            fflush(stderr);
            return;
        }
        return;
'''
    text = replace_once(text, old, new, "three-frame HWord input sequence")
    required = {
        "HRT M10 APPKIT: staged toolbar new-document click": 1,
        "HRT M10 APPKIT: staged document focus click": 1,
        "HRT M10 APPKIT: staged text input after focus": 1,
        "HRT M8 APPKIT: posted deterministic focus click, key and mouse events": 2,
        "g_m10_synthetic_stage = 3u": 1,
        "NSMaxY(bounds) - 163.0": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"input-stage marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )
    path.write_text(text, encoding="utf-8")


def retime_captures(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "!g_m10_pre_capture_done && g_presented_frames == 1u &&",
        "!g_m10_pre_capture_done && g_presented_frames == 3u &&",
        "focused pre-input capture frame",
    )
    text = replace_once(
        text,
        "if (g_m10_input_injection_frame == 0u &&\n"
        "        synthetic_input != NULL && strcmp(synthetic_input, \"1\") == 0) {",
        "if (g_m10_input_injection_frame == 0u &&\n"
        "        g_presented_frames >= 3u &&\n"
        "        synthetic_input != NULL && strcmp(synthetic_input, \"1\") == 0) {",
        "text-stage injection frame",
    )
    required = {
        "g_presented_frames == 3u": 1,
        "g_presented_frames >= 3u": 1,
        "g_m10_input_injection_frame + 2u": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"capture marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} SOURCE.m OUTPUT.m")
    output = Path(sys.argv[2])
    run_locked_generator()
    split_input_stages(Path("runtime/m8/appkit_input.m"))
    retime_captures(output)


if __name__ == "__main__":
    main()
