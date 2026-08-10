#!/usr/bin/env python3
"""Inject a signal-safe Linux guest-to-AppKit host-call transport.

The reserved Linux syscall is first caught by the existing UD2/SIGILL bridge.
The signal handler only snapshots the guest machine state and redirects signal
return to a dedicated host stack.  Objective-C/AppKit then runs in ordinary
thread context rather than inside a signal handler.  An assembly epilogue
restores x87/SSE state, guest GS TLS, Linux syscall registers, and the original
guest stack before continuing after the trapped instruction.
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
        '#include "hrt_m3.h"\n'
        '#include "appkit_adapter.h"\n'
        '#include "hostcall_trampoline.h"\n',
        "M6 deferred host-call includes",
    )

    scheduler = r'''
static void schedule_m6_appkit_hostcall(x86_thread_state64_t *state,
                                        uint64_t trapped_rip) {
    HrtM6PendingHostcall *pending = &g_hrt_m6_pending;
    if (pending->active != 0u) {
        static const char message[] =
            "hrt-m6: nested deferred host call\n";
        fail_from_signal(message, sizeof(message) - 1u, 125);
    }

    uintptr_t guest_gs = switch_to_host_context();
    if (guest_gs == 0u) guest_gs = g_guest_fs_base;

    pending->opcode = state->__rdi;
    pending->argument1 = state->__rsi;
    pending->argument2 = state->__rdx;
    pending->argument3 = state->__r10;
    pending->argument4 = state->__r8;
    pending->argument5 = state->__r9;
    pending->guest_gs_base = (uint64_t)guest_gs;
    pending->resume_rip = trapped_rip + 2u;
    pending->resume_rflags = state->__rflags;
    pending->guest_rsp = state->__rsp;
    pending->guest_rbx = state->__rbx;
    pending->guest_rbp = state->__rbp;
    pending->guest_r12 = state->__r12;
    pending->guest_r13 = state->__r13;
    pending->guest_r14 = state->__r14;
    pending->guest_r15 = state->__r15;
    pending->guest_rdi = state->__rdi;
    pending->guest_rsi = state->__rsi;
    pending->guest_rdx = state->__rdx;
    pending->guest_r10 = state->__r10;
    pending->guest_r8 = state->__r8;
    pending->guest_r9 = state->__r9;
    pending->result = -1098;
    pending->active = 1u;

    uintptr_t host_stack_top =
        (uintptr_t)g_hrt_m6_hostcall_stack + HRT_M6_HOSTCALL_STACK_SIZE;
    host_stack_top &= ~(uintptr_t)0x0fu;

    state->__rip = (uint64_t)(uintptr_t)hrt_m6_deferred_hostcall_entry;
    state->__rsp = (uint64_t)host_stack_top;
    g_in_handler = 0;
}

'''
    text = replace_once(
        text,
        "static void sigill_handler(int signo, siginfo_t *info, "
        "void *context_pointer) {\n",
        scheduler
        + "static void sigill_handler(int signo, siginfo_t *info, "
        "void *context_pointer) {\n",
        "M6 deferred scheduler",
    )

    # Older bridges placed poll first in the syscall switch.  The mature
    # event-loop bridge may prepend epoll/tgkill cases, so anchor only on the
    # unique dispatcher switch instead of depending on case ordering.
    text = replace_once(
        text,
        "    switch (state->__rax) {\n",
        "    switch (state->__rax) {\n"
        "        case HRT_M6_HOSTCALL_SYSCALL:\n"
        "            schedule_m6_appkit_hostcall(state, rip);\n"
        "            return;\n",
        "M6 deferred dispatch",
    )

    required_counts = {
        '#include "appkit_adapter.h"': 1,
        '#include "hostcall_trampoline.h"': 1,
        "case HRT_M6_HOSTCALL_SYSCALL:": 1,
        "schedule_m6_appkit_hostcall(": 2,
        "hrt_m6_deferred_hostcall_entry": 1,
        "g_hrt_m6_hostcall_stack": 1,
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
