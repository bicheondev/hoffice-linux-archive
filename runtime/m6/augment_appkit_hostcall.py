#!/usr/bin/env python3
"""Inject the M6 Linux guest-to-AppKit host-call transport into M3.

The Linux guest issues a reserved syscall number.  Prepatching turns that
instruction into the runtime's existing UD2 trap, and this generated switch
case restores host TLS before entering Objective-C/AppKit.  Results are
reported through the guest RAX just like any translated Linux syscall.
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
        '#include "hrt_m3.h"\n',
        '#include "hrt_m3.h"\n#include "appkit_adapter.h"\n',
        "AppKit adapter include",
    )

    bridge = r'''
static void raw_trace_m6_hostcall(uint64_t opcode, int64_t result) {
    char buffer[192];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "hrt-m6: host-call opcode=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), opcode);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  " result=");
    if (result < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-result));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)result);
    }
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor);
}

static int64_t bridge_m6_appkit_hostcall(uint64_t opcode,
                                         uint64_t argument1,
                                         uint64_t argument2,
                                         uint64_t argument3,
                                         uint64_t argument4,
                                         uint64_t argument5) {
    uintptr_t guest = switch_to_host_context();
    int64_t result = hrt_m6_appkit_hostcall(
        opcode, argument1, argument2, argument3, argument4, argument5);
    restore_guest_context(guest);
    raw_trace_m6_hostcall(opcode, result);
    return result;
}

'''
    text = replace_once(
        text,
        "static void sigill_handler(int signo, siginfo_t *info, "
        "void *context_pointer) {\n",
        bridge
        + "static void sigill_handler(int signo, siginfo_t *info, "
        "void *context_pointer) {\n",
        "M6 host-call bridge",
    )

    text = replace_once(
        text,
        "    switch (state->__rax) {\n"
        "        case LINUX_SYS_POLL:\n",
        "    switch (state->__rax) {\n"
        "        case HRT_M6_HOSTCALL_SYSCALL:\n"
        "            result = bridge_m6_appkit_hostcall(\n"
        "                state->__rdi, state->__rsi, state->__rdx,\n"
        "                state->__r10, state->__r8, state->__r9);\n"
        "            break;\n"
        "        case LINUX_SYS_POLL:\n",
        "M6 host-call dispatch",
    )

    required_counts = {
        '#include "appkit_adapter.h"': 1,
        "case HRT_M6_HOSTCALL_SYSCALL:": 1,
        "bridge_m6_appkit_hostcall(": 2,
        "hrt-m6: host-call opcode=": 1,
        "hrt_m6_appkit_hostcall(": 1,
    }
    for marker, expected in required_counts.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"injected marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
