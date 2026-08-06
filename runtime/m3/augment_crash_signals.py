#!/usr/bin/env python3
"""Extend the generated M3 bridge with durable crash-boundary diagnostics."""
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
        "static volatile sig_atomic_t g_in_handler;\n",
        "static volatile sig_atomic_t g_in_handler;\n"
        "static volatile uint64_t g_last_linux_syscall;\n"
        "static volatile uint64_t g_last_linux_syscall_rip;\n",
        "last syscall state",
    )

    text = replace_once(
        text,
        "    APPEND_LITERAL(\" rsp=\"); APPEND_HEX(state->__rsp);\n",
        "    APPEND_LITERAL(\" rsp=\"); APPEND_HEX(state->__rsp);\n"
        "    APPEND_LITERAL(\" last-syscall=\");\n"
        "    cursor = trace_append_decimal(\n"
        "        buffer, cursor, sizeof(buffer), g_last_linux_syscall);\n"
        "    APPEND_LITERAL(\" last-syscall-rip=\");\n"
        "    APPEND_HEX(g_last_linux_syscall_rip);\n",
        "crash report last syscall",
    )

    text = replace_once(
        text,
        "    raw_trace_syscall(state->__rax, rip, state->__rdi, state->__rsi,\n",
        "    g_last_linux_syscall = state->__rax;\n"
        "    g_last_linux_syscall_rip = rip;\n"
        "    raw_trace_syscall(state->__rax, rip, state->__rdi, state->__rsi,\n",
        "record last syscall",
    )

    install_anchor = '''    if (sigaction(SIGSEGV, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGSEGV)");
    }
'''
    install_replacement = '''    if (sigaction(SIGSEGV, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGSEGV)");
    }
    if (sigaction(SIGTRAP, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGTRAP)");
    }
    if (sigaction(SIGABRT, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGABRT)");
    }
    if (sigaction(SIGFPE, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGFPE)");
    }
'''
    text = replace_once(text, install_anchor, install_replacement,
                        "additional crash signals")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
