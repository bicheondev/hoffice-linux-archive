#!/usr/bin/env python3
"""Inject single-process Linux tgkill support into the M3 bridge.

The current clean-room runtime has one host thread.  HWord/Qt uses tgkill to
raise SIGABRT after a fatal initialization error.  Translating self-directed
signals prevents the guest from falling through an ENOSYS abort path and
preserves the runtime's structured crash evidence.
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
    if "host_tgkill_bridge(" in text:
        raise SystemExit("tgkill bridge is already present")

    text = replace_once(
        text,
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n",
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n"
        "#ifndef LINUX_SYS_TGKILL\n"
        "#define LINUX_SYS_TGKILL UINT64_C(234)\n"
        "#endif\n",
        "tgkill constant",
    )

    bridge = r'''
static int host_signal_from_linux(int linux_signal) {
    switch (linux_signal) {
        case 0: return 0;
        case 1: return SIGHUP;
        case 2: return SIGINT;
        case 3: return SIGQUIT;
        case 4: return SIGILL;
        case 5: return SIGTRAP;
        case 6: return SIGABRT;
        case 7: return SIGBUS;
        case 8: return SIGFPE;
        case 9: return SIGKILL;
        case 10: return SIGUSR1;
        case 11: return SIGSEGV;
        case 12: return SIGUSR2;
        case 13: return SIGPIPE;
        case 14: return SIGALRM;
        case 15: return SIGTERM;
        case 17: return SIGCHLD;
        case 18: return SIGCONT;
        case 19: return SIGSTOP;
        case 20: return SIGTSTP;
        case 21: return SIGTTIN;
        case 22: return SIGTTOU;
        default: return -1;
    }
}

static int64_t host_tgkill_bridge(int process_id, int thread_id,
                                  int linux_signal) {
    uintptr_t guest = switch_to_host_context();
    pid_t self = getpid();
    restore_guest_context(guest);
    if (process_id != (int)self || thread_id != (int)self) {
        return -LINUX_ESRCH;
    }

    int host_signal = host_signal_from_linux(linux_signal);
    if (host_signal < 0) return -LINUX_EINVAL;
    if (host_signal == 0) return 0;

    guest = switch_to_host_context();
    errno = 0;
    int result = kill(self, host_signal);
    int saved_errno = errno;
    restore_guest_context(guest);
    if (result != 0) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }
    return 0;
}

'''
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        bridge + "static int64_t host_close_bridge(int fd) {\n",
        "tgkill bridge",
    )

    text = replace_once(
        text,
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "        case LINUX_SYS_TGKILL:\n"
        "            result = host_tgkill_bridge(\n"
        "                (int)state->__rdi, (int)state->__rsi,\n"
        "                (int)state->__rdx);\n"
        "            break;\n"
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "tgkill dispatch",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
