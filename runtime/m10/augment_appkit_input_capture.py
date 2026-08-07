#!/usr/bin/env python3
"""Add deterministic staged input and pre/post captures to the M8 adapter.

M10 uses the already-proven M8 AppKit event transport, but the original test
posted a plain ``a`` before HWord had created an editable document and captured
its baseline before WindowServer had displayed the first real BGRA frame.
This generator now does two tightly scoped things for the exact ``Word``
window:

* stage ``Ctrl+N`` on the first presented frame, then click the document area
  and type ``a`` on the following frame; and
* pump WindowServer before the baseline capture and wait two additional frames
  before the post-input capture.

The ordinary M8 one-shot sequence is unchanged for every other window.  The
input-source rewrite is fail-closed and idempotent within a single checkout.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def patch_input_source(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "HRT M10 APPKIT: staged Ctrl+N" in text:
        return

    text = replace_once(
        text,
        "static BOOL g_synthetic_input_injected;\n",
        "static BOOL g_synthetic_input_injected;\n"
        "static unsigned int g_m10_synthetic_stage;\n",
        "M10 synthetic stage state",
    )
    text = replace_once(
        text,
        "    g_synthetic_input_injected = NO;\n"
        "    memset(g_events, 0, sizeof(g_events));\n",
        "    g_synthetic_input_injected = NO;\n"
        "    g_m10_synthetic_stage = 0u;\n"
        "    memset(g_events, 0, sizeof(g_events));\n",
        "M10 synthetic stage reset",
    )

    key_helper_anchor = '''static NSEvent *synthetic_mouse(NSEventType type, NSWindow *window,
                                NSPoint location, NSInteger event_number) {
'''
    key_helper = r'''static NSEvent *m10_synthetic_key(NSEventType type, NSWindow *window,
                                      NSString *characters,
                                      NSEventModifierFlags modifiers,
                                      unsigned short key_code) {
    return [NSEvent keyEventWithType:type
                           location:NSZeroPoint
                      modifierFlags:modifiers
                          timestamp:NSProcessInfo.processInfo.systemUptime
                       windowNumber:window.windowNumber
                            context:nil
                         characters:characters
        charactersIgnoringModifiers:characters
                           isARepeat:NO
                             keyCode:key_code];
}

static NSEvent *synthetic_mouse(NSEventType type, NSWindow *window,
                                NSPoint location, NSInteger event_number) {
'''
    text = replace_once(text, key_helper_anchor, key_helper,
                        "M10 parametrized key helper")

    injection_anchor = '''    NSWindow *window = (__bridge NSWindow *)window_pointer;
    if (window == nil || window != g_input_window) return;
    g_synthetic_input_injected = YES;

    const NSRect bounds = window.contentView != nil
'''
    injection = r'''    NSWindow *window = (__bridge NSWindow *)window_pointer;
    if (window == nil || window != g_input_window) return;

    /*
     * The first genuine HWord editor window initially has no document.  A
     * plain key event is therefore correctly ignored.  Drive the normal HWord
     * New command on one frame, then focus the document canvas and type on the
     * next frame.  Keeping the stages frame-separated lets Qt finish the
     * document creation synchronously before the text event is delivered.
     */
    if ([window.title isEqualToString:@"Word"]) {
        [NSApp activateIgnoringOtherApps:YES];
        [window makeKeyAndOrderFront:nil];
        [window makeMainWindow];
        [window makeKeyWindow];
        if (window.contentView != nil)
            [window makeFirstResponder:window.contentView];

        if (g_m10_synthetic_stage == 0u) {
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

        if (g_m10_synthetic_stage == 1u) {
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
    }

    g_synthetic_input_injected = YES;

    const NSRect bounds = window.contentView != nil
'''
    text = replace_once(text, injection_anchor, injection,
                        "M10 staged Word input")

    required = {
        "g_m10_synthetic_stage": 6,
        "HRT M10 APPKIT: staged Ctrl+N": 1,
        "HRT M10 APPKIT: staged document click and text input": 1,
        "NSEventModifierFlagControl": 2,
        "m10_synthetic_key": 3,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"input marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M10 APPKIT:" in text:
        raise SystemExit("M10 input capture is already present")

    patch_input_source(Path("runtime/m8/appkit_input.m"))

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

    /* Let WindowServer publish the just-presented BGRA surface first. */
    pump_events(0.05);

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
                "HRT M10 APPKIT: staged synthetic input armed frame=%llu window=%ld\n",
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
        g_presented_frames >= g_m10_input_injection_frame + 2u &&
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
                        "M10 staged pre/post frame capture")

    required = {
        "g_m10_input_injection_frame": 8,
        "HRT M10 APPKIT: pre-input capture": 1,
        "HRT M10 APPKIT: staged synthetic input armed": 1,
        "HRT M10 APPKIT: post-input capture": 1,
        "HRT_M10_PRE_INPUT_CAPTURE_PATH": 1,
        "HRT_M10_POST_INPUT_CAPTURE_PATH": 1,
        "hrt_m8_input_inject_if_requested": 1,
        "g_m10_input_injection_frame + 2u": 1,
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
