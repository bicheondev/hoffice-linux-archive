#!/usr/bin/env python3
"""Add a fail-closed, runtime-selectable empty-open compatibility probe.

The exact HWord document path is copied and traversed successfully, but three
stage-1 ``openat(AT_FDCWD, "", ...)`` calls immediately precede the native
validation-error dialog.  This diagnostic transform does not credit those
calls as the root cause.  It permits controlled A/B replays by replacing only
a selected empty-path ordinal with the already materialized
``Document[0].hwdt`` path.

``HRT_M11_EMPTY_OPEN_SUBSTITUTE`` selects the experiment: unset/``0`` observes,
``1`` through ``3`` replace one ordinal, and ``99`` or ``all`` replace every
stage-1 empty open.  The environment is read only after restoring the Darwin
pthread/TSD context.  Non-empty paths and all other stages are unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def function_bounds(text: str, signature: str) -> tuple[int, int, int]:
    count = text.count(signature)
    if count != 1:
        raise SystemExit(f"host-open signature: expected one, found {count}")
    start = text.index(signature)
    opening = start + signature.rfind("{")
    depth = 0
    closing = -1
    for index in range(opening, len(text)):
        value = text[index]
        if value == "{":
            depth += 1
        elif value == "}":
            depth -= 1
            if depth == 0:
                closing = index + 1
                break
    if closing < 0:
        raise SystemExit("host-open function has no matching close brace")
    return start, opening, closing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    generator = Path(__file__).with_name(
        "augment_hword_document_io_trace_v6.py"
    )
    if not generator.is_file():
        raise SystemExit(f"escaped frame-chain generator not found: {generator}")

    with tempfile.TemporaryDirectory(prefix="hrt-m11-empty-open-") as temporary:
        intermediate = Path(temporary) / "syscall_bridge_framectx.c"
        subprocess.run(
            [sys.executable, str(generator), str(args.source), str(intermediate)],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M11 EMPTYOPEN:" in text:
        raise SystemExit("empty-open compatibility probe is already present")
    if "HRT M11 FRAMECTX:" not in text:
        raise SystemExit("canonical frame-chain tracer was not generated")

    signature = '''static int64_t host_open_bridge(int directory_fd, const char *guest_path,
                                uint64_t flags, uint64_t mode,
                                const M11OpenContext *open_context) {
'''
    start, _opening, closing = function_bounds(text, signature)
    function = text[start:closing]
    body_start = function.index("{") + 1
    original_body = function[body_start:]
    guest_path_count = len(re.findall(r"\bguest_path\b", original_body))
    if guest_path_count < 2:
        raise SystemExit(
            f"host-open body: expected at least two guest_path uses, "
            f"found {guest_path_count}")
    rewritten_body, replacement_count = re.subn(
        r"\bguest_path\b", "effective_guest_path", original_body)
    if replacement_count != guest_path_count:
        raise SystemExit(
            f"host-open body: expected {guest_path_count} identifier rewrites, "
            f"performed {replacement_count}")
    rewritten_body = '''
    unsigned int empty_open_ordinal = 0u;
    int empty_open_substituted = 0;
    const char *effective_guest_path = m11_empty_open_effective_path(
        guest_path, &empty_open_ordinal, &empty_open_substituted);
''' + rewritten_body
    rewritten_function = function[:body_start] + rewritten_body
    text = text[:start] + rewritten_function + text[closing:]

    helpers = r'''static const char g_m11_empty_open_template_path[] =
    "/tmp/hrt-home/.hnc/User/Hword/Template/ko-KR/Document[0].hwdt";
static volatile sig_atomic_t g_m11_empty_open_mode = -2;
static volatile sig_atomic_t g_m11_empty_open_ordinal;
static unsigned int g_m11_empty_open_trace_count;
#define M11_EMPTY_OPEN_TRACE_LIMIT 16u

static int m11_empty_open_selected_mode(void) {
    const sig_atomic_t cached = g_m11_empty_open_mode;
    if (cached != -2) return (int)cached;

    uintptr_t guest_context = switch_to_host_context();
    const char *value = getenv("HRT_M11_EMPTY_OPEN_SUBSTITUTE");
    int selected = 0;
    if (value != NULL) {
        if (value[0] == 'a' && value[1] == 'l' && value[2] == 'l' &&
            value[3] == '\0') {
            selected = 99;
        } else {
            unsigned int parsed = 0u;
            const char *cursor = value;
            while (*cursor >= '0' && *cursor <= '9') {
                if (parsed > 1000u) {
                    parsed = 0u;
                    break;
                }
                parsed = parsed * 10u + (unsigned int)(*cursor - '0');
                ++cursor;
            }
            if (*cursor == '\0' &&
                (parsed == 0u || parsed == 1u || parsed == 2u ||
                 parsed == 3u || parsed == 99u)) {
                selected = (int)parsed;
            }
        }
    }
    restore_guest_context(guest_context);
    g_m11_empty_open_mode = (sig_atomic_t)selected;
    return selected;
}

static void m11_empty_open_emit(unsigned int ordinal, int selected,
                                int substituted, uint64_t original_pointer) {
    if (g_m11_empty_open_trace_count >= M11_EMPTY_OPEN_TRACE_LIMIT)
        return;
    ++g_m11_empty_open_trace_count;
    char buffer[768];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M11 EMPTYOPEN: ordinal=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), ordinal);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " mode=");
    cursor = m11_docio_append_signed(buffer, cursor, sizeof(buffer), selected);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " substituted=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                  substituted ? 1u : 0u);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " original-pointer=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), original_pointer);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " replacement=");
    cursor = trace_append_literal(
        buffer, cursor, sizeof(buffer),
        substituted ? g_m11_empty_open_template_path : "(none)");
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static const char *m11_empty_open_effective_path(
    const char *guest_path, unsigned int *ordinal_output,
    int *substituted_output) {
    if (ordinal_output != NULL) *ordinal_output = 0u;
    if (substituted_output != NULL) *substituted_output = 0;
    if (g_m11_docio_stage != 1 || guest_path == NULL || guest_path[0] != '\0')
        return guest_path;

    const unsigned int ordinal = (unsigned int)__sync_add_and_fetch(
        &g_m11_empty_open_ordinal, 1);
    const int selected = m11_empty_open_selected_mode();
    const int substituted = selected == 99 || selected == (int)ordinal;
    if (ordinal_output != NULL) *ordinal_output = ordinal;
    if (substituted_output != NULL) *substituted_output = substituted;
    m11_empty_open_emit(ordinal, selected, substituted,
                        (uint64_t)(uintptr_t)guest_path);
    return substituted ? g_m11_empty_open_template_path : guest_path;
}

static int64_t host_open_bridge(int directory_fd, const char *guest_path,
                                uint64_t flags, uint64_t mode,
                                const M11OpenContext *open_context) {
'''
    text = replace_once(text, signature, helpers,
                        "empty-open helper insertion")

    required = {
        "HRT M11 EMPTYOPEN:": 1,
        "HRT_M11_EMPTY_OPEN_SUBSTITUTE": 1,
        "M11_EMPTY_OPEN_TRACE_LIMIT 16u": 1,
        "m11_empty_open_effective_path(": 2,
        "g_m11_empty_open_template_path": 3,
        "__sync_add_and_fetch(": 1,
        "effective_guest_path": guest_path_count + 1,
        "const M11OpenContext *open_context": 2,
        "HRT M11 FRAMECTX:": 1,
        "M11_DOCIO_FRAME_COUNT 8u": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"empty-open marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
