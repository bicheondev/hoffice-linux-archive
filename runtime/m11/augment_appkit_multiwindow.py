#!/usr/bin/env python3
"""Add bounded multi-window AppKit support to the exact M11 host adapter.

The full HOffice product closure reaches the real New-document path and creates
an empty-titled Qt ``Dialog`` while the main-window mouse-up is still executing.
The proven M6 adapter was intentionally single-window: a second CREATE replaced
the first NSWindow, and the QPA therefore suppressed the dialog entirely.  The
outer input drain then remained blocked inside an invisible modal loop.

This transform is applied after all existing M8/M10/M11 adapter generators.  It
preserves their reviewed globals as aliases for the currently selected native
window, but stores those globals in a per-window record before switching.  The
existing host-call ABI already carries a WindowServer handle for PRESENT,
QUERY, CAPTURE and DESTROY, so no guest ABI changes are required.

For this first closure diagnostic the original main HWord window remains the
sole AppKit input owner.  Secondary dialogs receive independent NSWindows and
BGRA surfaces without resetting or stealing the main input queue.  Their first
real frame is captured through ``HRT_M11_MODAL_CAPTURE_PATH``.  This proves the
modal UI before a later, separately audited dialog-input policy is introduced.
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
    if "HRT M11 APPKIT: registered native window" in text:
        raise SystemExit("M11 AppKit multi-window support is already present")

    class_anchor = '''@end

static NSWindow *g_window;
'''
    class_replacement = '''@end

@interface HrtM11WindowRecord : NSObject
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) HrtM7SurfaceView *surfaceView;
@property(nonatomic) uint64_t presentedFrames;
@property(nonatomic) uint64_t inputInjectionFrame;
@property(nonatomic) BOOL preCaptureDone;
@property(nonatomic) BOOL postCaptureDone;
@end

@implementation HrtM11WindowRecord
@end

static NSWindow *g_window;
'''
    text = replace_once(text, class_anchor, class_replacement,
                        "per-window record class")

    global_anchor = '''static BOOL g_m10_post_capture_done;
static _Atomic unsigned int g_initialized;
'''
    global_replacement = '''static BOOL g_m10_post_capture_done;
static NSMutableDictionary<NSNumber *, HrtM11WindowRecord *> *g_m11_windows;
static HrtM11WindowRecord *g_m11_active_record;
static __weak NSWindow *g_m11_input_window;
static _Atomic unsigned int g_initialized;
'''
    text = replace_once(text, global_anchor, global_replacement,
                        "multi-window globals")

    helper_anchor = '''static HrtM6Mailbox g_mailbox;

static BOOL on_appkit_thread(void) {
'''
    helpers = r'''static HrtM6Mailbox g_mailbox;

static NSMutableDictionary<NSNumber *, HrtM11WindowRecord *> *
m11_window_registry(void) {
    if (g_m11_windows == nil)
        g_m11_windows = [[NSMutableDictionary alloc] init];
    return g_m11_windows;
}

static void m11_store_active_record(void) {
    if (g_m11_active_record == nil)
        return;
    g_m11_active_record.window = g_window;
    g_m11_active_record.surfaceView = g_surface_view;
    g_m11_active_record.presentedFrames = g_presented_frames;
    g_m11_active_record.inputInjectionFrame = g_m10_input_injection_frame;
    g_m11_active_record.preCaptureDone = g_m10_pre_capture_done;
    g_m11_active_record.postCaptureDone = g_m10_post_capture_done;
}

static void m11_clear_active_aliases(void) {
    g_window = nil;
    g_surface_view = nil;
    g_presented_frames = 0u;
    g_m10_input_injection_frame = 0u;
    g_m10_pre_capture_done = NO;
    g_m10_post_capture_done = NO;
}

static void m11_load_record(HrtM11WindowRecord *record) {
    g_m11_active_record = record;
    if (record == nil) {
        m11_clear_active_aliases();
        return;
    }
    g_window = record.window;
    g_surface_view = record.surfaceView;
    g_presented_frames = record.presentedFrames;
    g_m10_input_injection_frame = record.inputInjectionFrame;
    g_m10_pre_capture_done = record.preCaptureDone;
    g_m10_post_capture_done = record.postCaptureDone;
}

static HrtM11WindowRecord *m11_record_for_number(uint64_t number) {
    if (number == 0u || number > (uint64_t)NSIntegerMax)
        return nil;
    return [m11_window_registry()
        objectForKey:@((NSInteger)number)];
}

static BOOL m11_select_window_number(uint64_t number) {
    if (number == 0u)
        return g_window != nil;
    HrtM11WindowRecord *record = m11_record_for_number(number);
    if (record == nil)
        return NO;
    if (record != g_m11_active_record) {
        m11_store_active_record();
        m11_load_record(record);
    }
    return g_window != nil &&
        (uint64_t)g_window.windowNumber == number;
}

static void m11_restore_input_window(void) {
    if (g_m11_input_window == nil) {
        m11_load_record(nil);
        return;
    }
    HrtM11WindowRecord *record =
        m11_record_for_number((uint64_t)g_m11_input_window.windowNumber);
    m11_load_record(record);
}

static BOOL on_appkit_thread(void) {
'''
    text = replace_once(text, helper_anchor, helpers,
                        "multi-window helpers")

    reset_anchor = '''static void reset_window(void) {
    hrt_m8_input_reset();
    if (g_window != nil) {
        [g_window orderOut:nil];
        [g_window close];
    }
    g_window = nil;
    g_surface_view = nil;
    g_presented_frames = 0u;
    g_m10_input_injection_frame = 0u;
    g_m10_pre_capture_done = NO;
    g_m10_post_capture_done = NO;
}
'''
    reset_replacement = r'''static void reset_window(void) {
    NSWindow *closing_window = g_window;
    const NSInteger closing_number = closing_window != nil
        ? closing_window.windowNumber : 0;
    const BOOL closing_input = closing_window != nil &&
        closing_window == g_m11_input_window;
    if (closing_input) {
        hrt_m8_input_reset();
        g_m11_input_window = nil;
    }
    if (closing_window != nil) {
        [closing_window orderOut:nil];
        [closing_window close];
    }
    if (closing_number > 0) {
        [m11_window_registry()
            removeObjectForKey:@(closing_number)];
    }
    g_m11_active_record = nil;
    m11_clear_active_aliases();
    m11_restore_input_window();
    fprintf(stderr,
            "HRT M11 APPKIT: destroyed native window=%ld input-owner=%d remaining=%lu\n",
            (long)closing_number, closing_input ? 1 : 0,
            (unsigned long)m11_window_registry().count);
    fflush(stderr);
}
'''
    text = replace_once(text, reset_anchor, reset_replacement,
                        "per-window reset")

    create_anchor = '''    reset_window();
    NSWindowStyleMask style = NSWindowStyleMaskTitled |
'''
    create_replacement = '''    m11_store_active_record();
    HrtM11WindowRecord *previous_record = g_m11_active_record;
    g_m11_active_record = nil;
    m11_clear_active_aliases();
    NSWindowStyleMask style = NSWindowStyleMaskTitled |
'''
    text = replace_once(text, create_anchor, create_replacement,
                        "non-destructive window creation")

    text = replace_once(
        text,
        '    if (g_window == nil) return -1005;\n',
        '    if (g_window == nil) {\n'
        '        m11_load_record(previous_record);\n'
        '        return -1005;\n'
        '    }\n',
        "window allocation rollback",
    )
    text = replace_once(
        text,
        '    if (g_surface_view == nil) { reset_window(); return -1007; }\n',
        '    if (g_surface_view == nil) {\n'
        '        [g_window orderOut:nil];\n'
        '        [g_window close];\n'
        '        m11_clear_active_aliases();\n'
        '        m11_load_record(previous_record);\n'
        '        return -1007;\n'
        '    }\n',
        "surface allocation rollback",
    )

    attach_anchor = '''    const int input_result = hrt_m8_input_attach((__bridge void *)g_window);
    fprintf(stderr, "HRT M8 APPKIT: attach result=%d\n", input_result);
    fflush(stderr);
'''
    attach_replacement = r'''    int input_result = 0;
    const BOOL claim_input = g_m11_input_window == nil;
    if (claim_input) {
        input_result = hrt_m8_input_attach((__bridge void *)g_window);
        if (input_result == 0)
            g_m11_input_window = g_window;
    }
    fprintf(stderr,
            "HRT M8 APPKIT: attach result=%d claimed=%d window=%ld input-window=%ld\n",
            input_result, claim_input ? 1 : 0,
            (long)g_window.windowNumber,
            g_m11_input_window != nil
                ? (long)g_m11_input_window.windowNumber : 0L);
    fflush(stderr);
'''
    text = replace_once(text, attach_anchor, attach_replacement,
                        "primary-only input attachment")

    return_anchor = '''    NSInteger number = g_window.windowNumber;
    return number > 0 ? (int64_t)number : -1006;
}
'''
    return_replacement = r'''    NSInteger number = g_window.windowNumber;
    if (number <= 0) {
        if (g_window == g_m11_input_window) {
            hrt_m8_input_reset();
            g_m11_input_window = nil;
        }
        [g_window orderOut:nil];
        [g_window close];
        m11_clear_active_aliases();
        m11_load_record(previous_record);
        return -1006;
    }
    HrtM11WindowRecord *record = [[HrtM11WindowRecord alloc] init];
    record.window = g_window;
    record.surfaceView = g_surface_view;
    record.presentedFrames = g_presented_frames;
    record.inputInjectionFrame = g_m10_input_injection_frame;
    record.preCaptureDone = g_m10_pre_capture_done;
    record.postCaptureDone = g_m10_post_capture_done;
    [m11_window_registry() setObject:record forKey:@(number)];
    g_m11_active_record = record;
    fprintf(stderr,
            "HRT M11 APPKIT: registered native window=%ld title=%s input-owner=%d total=%lu\n",
            (long)number, guest_title,
            g_window == g_m11_input_window ? 1 : 0,
            (unsigned long)m11_window_registry().count);
    fflush(stderr);
    return (int64_t)number;
}
'''
    text = replace_once(text, return_anchor, return_replacement,
                        "native record registration")

    present_anchor = '''    if (!on_appkit_thread()) return -1020;
    if (g_window == nil || g_surface_view == nil) return -1021;
    const NSInteger number = g_window.windowNumber;
    if (expected_number != 0u && expected_number != (uint64_t)number) return -1022;
'''
    present_replacement = '''    if (!on_appkit_thread()) return -1020;
    if (!m11_select_window_number(expected_number)) return -1022;
    if (g_window == nil || g_surface_view == nil) return -1021;
    const NSInteger number = g_window.windowNumber;
'''
    text = replace_once(text, present_anchor, present_replacement,
                        "per-handle BGRA presentation")

    query_anchor = '''static int64_t query_window(uint64_t expected_number) {
    if (!on_appkit_thread() || g_window == nil) return 0;
    const NSInteger number = g_window.windowNumber;
    if (expected_number != 0u && expected_number != (uint64_t)number) return -1010;
'''
    query_replacement = '''static int64_t query_window(uint64_t expected_number) {
    if (!on_appkit_thread()) return 0;
    if (!m11_select_window_number(expected_number)) return -1010;
    if (g_window == nil) return 0;
    const NSInteger number = g_window.windowNumber;
'''
    text = replace_once(text, query_anchor, query_replacement,
                        "per-handle window query")

    capture_anchor = '''            case HRT_M6_OP_CAPTURE_WINDOW: {
                if (g_window == nil) return 0;
                const char *path = NULL;
                if (g_presented_frames > 0u) path = getenv("HRT_M7_CAPTURE_PATH");
                if (path == NULL || path[0] == '\\0') path = getenv("HRT_M6_CAPTURE_PATH");
                return capture_window((CGWindowID)g_window.windowNumber, path) ? 1 : 0;
            }
            case HRT_M6_OP_DESTROY_WINDOW:
                reset_window();
                pump_events(0.05);
                return 0;
'''
    capture_replacement = r'''            case HRT_M6_OP_CAPTURE_WINDOW: {
                if (!m11_select_window_number(argument1) || g_window == nil)
                    return 0;
                const char *path = NULL;
                if (g_window != g_m11_input_window)
                    path = getenv("HRT_M11_MODAL_CAPTURE_PATH");
                if ((path == NULL || path[0] == '\0') &&
                    g_presented_frames > 0u)
                    path = getenv("HRT_M7_CAPTURE_PATH");
                if (path == NULL || path[0] == '\0')
                    path = getenv("HRT_M6_CAPTURE_PATH");
                return capture_window(
                    (CGWindowID)g_window.windowNumber, path) ? 1 : 0;
            }
            case HRT_M6_OP_DESTROY_WINDOW:
                if (!m11_select_window_number(argument1))
                    return -1011;
                reset_window();
                pump_events(0.05);
                return 0;
'''
    text = replace_once(text, capture_anchor, capture_replacement,
                        "per-handle capture and destroy")

    text = replace_once(
        text,
        '    if (!g_m10_pre_capture_done && g_presented_frames == 3u &&\n',
        '    if (g_window == g_m11_input_window &&\n'
        '        !g_m10_pre_capture_done && g_presented_frames == 3u &&\n',
        "primary-only pre-input capture",
    )
    text = replace_once(
        text,
        '    if (g_m10_input_injection_frame == 0u &&\n'
        '        g_presented_frames >= 3u &&\n',
        '    if (g_window == g_m11_input_window &&\n'
        '        g_m10_input_injection_frame == 0u &&\n'
        '        g_presented_frames >= 3u &&\n',
        "primary-only staged input arm",
    )
    text = replace_once(
        text,
        '    if (!g_m10_post_capture_done &&\n'
        '        g_m10_input_injection_frame != 0u &&\n',
        '    if (g_window == g_m11_input_window &&\n'
        '        !g_m10_post_capture_done &&\n'
        '        g_m10_input_injection_frame != 0u &&\n',
        "primary-only post-input capture",
    )

    modal_anchor = '''    hrt_m8_input_inject_if_requested((__bridge void *)g_window);
    pump_events(0.05);

    const char *post_capture_path =
'''
    modal_replacement = r'''    hrt_m8_input_inject_if_requested((__bridge void *)g_window);
    pump_events(0.05);

    const char *modal_capture_path =
        getenv("HRT_M11_MODAL_CAPTURE_PATH");
    if (g_window != g_m11_input_window &&
        g_presented_frames == 1u &&
        modal_capture_path != NULL && modal_capture_path[0] != '\0') {
        const BOOL captured = capture_window(
            (CGWindowID)number, modal_capture_path);
        fprintf(stderr,
                "HRT M11 APPKIT: modal first-frame capture result=%d frame=%llu window=%ld title=%s path=%s\n",
                captured ? 1 : 0,
                (unsigned long long)g_presented_frames,
                (long)number, g_window.title.UTF8String,
                modal_capture_path);
        fflush(stderr);
    }

    const char *post_capture_path =
'''
    text = replace_once(text, modal_anchor, modal_replacement,
                        "secondary first-frame capture")

    required = {
        "@interface HrtM11WindowRecord": 1,
        "m11_window_registry(void)": 1,
        "m11_select_window_number(": 5,
        "HRT M11 APPKIT: registered native window": 1,
        "HRT M11 APPKIT: destroyed native window": 1,
        "HRT M11 APPKIT: modal first-frame capture": 1,
        "HRT_M11_MODAL_CAPTURE_PATH": 2,
        "g_window == g_m11_input_window &&": 3,
        "reset_window();\n    NSWindowStyleMask": 0,
        "if (expected_number != 0u && expected_number !=": 0,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"multi-window marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
