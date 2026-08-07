#!/usr/bin/env python3
"""Add the M8 AppKit input queue to the proven M7 adapter.

The generator is deliberately fail-closed.  Every insertion anchor must occur
exactly once so an upstream adapter change cannot silently produce a partially
wired input transport.  M10's staged synthetic replay uses this same transport
without changing the production path for real AppKit events.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '#import "appkit_adapter.h"\n',
        '#import "appkit_adapter.h"\n#import "appkit_input.h"\n',
        "M8 AppKit input include",
    )
    text = replace_once(
        text,
        'static void reset_window(void) {\n    if (g_window != nil) {\n',
        'static void reset_window(void) {\n'
        '    hrt_m8_input_reset();\n'
        '    if (g_window != nil) {\n',
        "M8 input reset",
    )
    text = replace_once(
        text,
        '    [NSApp activateIgnoringOtherApps:YES];\n    pump_events(0.25);\n',
        '    [NSApp activateIgnoringOtherApps:YES];\n'
        '    const int input_result = hrt_m8_input_attach((__bridge void *)g_window);\n'
        '    fprintf(stderr, "HRT M8 APPKIT: attach result=%d\\n", input_result);\n'
        '    fflush(stderr);\n'
        '    pump_events(0.25);\n',
        "M8 input attachment",
    )
    text = replace_once(
        text,
        '    [g_window displayIfNeeded];\n    pump_events(0.02);\n    fprintf(stderr,\n',
        '    [g_window displayIfNeeded];\n'
        '    hrt_m8_input_inject_if_requested((__bridge void *)g_window);\n'
        '    pump_events(0.05);\n'
        '    fprintf(stderr,\n',
        "M8 deterministic input injection",
    )
    text = replace_once(
        text,
        '            case HRT_M6_OP_PRESENT_BGRA:\n'
        '                return present_bgra((const unsigned char *)(uintptr_t)argument1,\n'
        '                                    argument2, argument3, argument4, argument5);\n'
        '            default:\n',
        '            case HRT_M6_OP_PRESENT_BGRA:\n'
        '                return present_bgra((const unsigned char *)(uintptr_t)argument1,\n'
        '                                    argument2, argument3, argument4, argument5);\n'
        '            case HRT_M8_OP_POLL_INPUT:\n'
        '                return hrt_m8_input_poll(\n'
        '                    (HrtM8InputEvent *)(uintptr_t)argument1, argument2);\n'
        '            default:\n',
        "M8 input host-call dispatch",
    )

    required = {
        '#import "appkit_input.h"': 1,
        'hrt_m8_input_reset();': 1,
        'hrt_m8_input_attach(': 1,
        'hrt_m8_input_inject_if_requested(': 1,
        'case HRT_M8_OP_POLL_INPUT:': 1,
        'hrt_m8_input_poll(': 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"M8 marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
