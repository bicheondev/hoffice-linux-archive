#!/usr/bin/env python3
"""Add deterministic pre/post-input window capture to the M8 AppKit adapter.

The M8 transport already converts AppKit NSEvents into synchronous Qt events.
For the first real HWord editor window, M10 also needs a durable rendering
boundary: one capture before the deterministic click/key sequence and one
capture after a later guest BGRA frame.  This generator keeps the M8 adapter
unchanged except for bounded capture state and fail-closed insertion anchors.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M10 APPKIT:" in text:
        raise SystemExit("M10 input capture is already present")

    text = replace_once(
        text,
        "static uint64_t g_presented_frames;\n",
        "static uint64_t g_presented_frames;\n"
        "static uint64_t g_m10_input_injection_frame;\n"
        "static BOOL g_m10_pre_capture_done;\n"
        "static BOOL g_m10_post_capture_done;\n",
        "M10 capture state",
    )

    text = replace_once(
        text,
        "    g_presented_frames = 0u;\n",
        "    g_presented_frames = 0u;\n"
        "    g_m10_input_injection_frame = 0u;\n"
        "    g_m10_pre_capture_done = NO;\n"
        "    g_m10_post_capture_done = NO;\n",
        "M10 capture reset",
    )

    frame_anchor = '''    [g_surface_view setNeedsDisplay:YES];
    [g_surface_view displayIfNeeded];
    [g_window displayIfNeeded];
    hrt_m8_input_inject_if_requested((__bridge void *)g_window);
    pump_events(0.05);
    fprintf(stderr,
'''
    frame_replacement = r'''    [g_surface_view setNeedsDisplay:YES];
    [g_surface_view displayIfNeeded];
    [g_window displayIfNeeded];

    const char *pre_capture_path =
        getenv("HRT_M10_PRE_INPUT_CAPTURE_PATH");
    if (!g_m10_pre_capture_done && g_presented_frames == 1u &&
        pre_capture_path != NULL && pre_capture_path[0] != '\0') {
        const BOOL captured = capture_window(
            (CGWindowID)number, pre_capture_path);
        g_m10_pre_capture_done = captured;
        fprintf(stderr,
                "HRT M10 APPKIT: pre-input capture result=%d frame=%llu window=%ld path=%s\n",
                captured ? 1 : 0,
                (unsigned long long)g_presented_frames,
                (long)number, pre_capture_path);
        fflush(stderr);
    }

    const char *synthetic_input = getenv("HRT_M8_SYNTHETIC_INPUT");
    if (g_m10_input_injection_frame == 0u &&
        synthetic_input != NULL && strcmp(synthetic_input, "1") == 0) {
        g_m10_input_injection_frame = g_presented_frames;
        fprintf(stderr,
                "HRT M10 APPKIT: synthetic input armed frame=%llu window=%ld\n",
                (unsigned long long)g_m10_input_injection_frame,
                (long)number);
        fflush(stderr);
    }
    hrt_m8_input_inject_if_requested((__bridge void *)g_window);
    pump_events(0.05);

    const char *post_capture_path =
        getenv("HRT_M10_POST_INPUT_CAPTURE_PATH");
    if (!g_m10_post_capture_done &&
        g_m10_input_injection_frame != 0u &&
        g_presented_frames > g_m10_input_injection_frame &&
        post_capture_path != NULL && post_capture_path[0] != '\0') {
        const BOOL captured = capture_window(
            (CGWindowID)number, post_capture_path);
        g_m10_post_capture_done = captured;
        fprintf(stderr,
                "HRT M10 APPKIT: post-input capture result=%d frame=%llu injection-frame=%llu window=%ld path=%s\n",
                captured ? 1 : 0,
                (unsigned long long)g_presented_frames,
                (unsigned long long)g_m10_input_injection_frame,
                (long)number, post_capture_path);
        fflush(stderr);
    }

    fprintf(stderr,
'''
    text = replace_once(text, frame_anchor, frame_replacement,
                        "M10 pre/post frame capture")

    required = {
        "g_m10_input_injection_frame": 8,
        "HRT M10 APPKIT: pre-input capture": 1,
        "HRT M10 APPKIT: synthetic input armed": 1,
        "HRT M10 APPKIT: post-input capture": 1,
        "HRT_M10_PRE_INPUT_CAPTURE_PATH": 1,
        "HRT_M10_POST_INPUT_CAPTURE_PATH": 1,
        "hrt_m8_input_inject_if_requested": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"M10 marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
