#!/usr/bin/env python3
"""Move clone-child GS switching into assembly and unblock guest traps.

The v2 generator establishes a real pthread-backed Linux clone context.  Two
host-runtime details must be handled before guest execution:

* GS is switched only after entering the already-bound assembly trampoline, so
  no Mach-O call executes with Linux TLS; and
* pthread_create is invoked from the SIGILL syscall handler.  POSIX threads
  inherit the creator's signal mask, including SIGILL's automatic handler-time
  block.  The child must therefore unblock the synchronous guest trap signals
  before its first patched Linux syscall.

The wrapper runs v2 unchanged, adds one host-GS signal-mask helper, checks it in
the child callback, removes the old pre-call raw_set_gs operation, and requires
the trampoline to own the TLS switch.  Every edit is exact-anchor and
fail-closed.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


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

    with tempfile.TemporaryDirectory(prefix="hrt-m10-clone-v4-") as temporary:
        intermediate = Path(temporary) / "clone-v2.c"
        subprocess.run(
            [
                sys.executable,
                "runtime/m10/augment_clone_compat_v2.py",
                str(args.source),
                str(intermediate),
            ],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    helper_anchor = '''static void *m10_clone_thread_start(void *opaque) {
'''
    helper = r'''static int m10_unblock_guest_trap_signals(void) {
    sigset_t signals;
    if (sigemptyset(&signals) != 0) return errno != 0 ? errno : EINVAL;
    const int trapped_signals[] = {
        SIGILL, SIGTRAP, SIGSEGV, SIGBUS, SIGABRT, SIGFPE,
    };
    for (size_t index = 0u;
         index < sizeof(trapped_signals) / sizeof(trapped_signals[0]);
         ++index) {
        if (sigaddset(&signals, trapped_signals[index]) != 0)
            return errno != 0 ? errno : EINVAL;
    }
    return pthread_sigmask(SIG_UNBLOCK, &signals, NULL);
}

static void *m10_clone_thread_start(void *opaque) {
'''
    text = replace_once(text, helper_anchor, helper,
                        "clone child signal-mask helper")

    setup_anchor = '''    context->host_gs = capture_host_gs_base();
    if (context->host_gs == 0u || m10_install_thread_altstack(context) != 0) {
'''
    setup_replacement = '''    context->host_gs = capture_host_gs_base();
    const int trap_mask_result = m10_unblock_guest_trap_signals();
    if (context->host_gs == 0u || trap_mask_result != 0 ||
        m10_install_thread_altstack(context) != 0) {
'''
    text = replace_once(text, setup_anchor, setup_replacement,
                        "clone child trap-mask setup")

    text = replace_once(
        text,
        '''    (void)raw_set_gs(context->guest_gs);
    hrt_m10_enter_clone_child(context);
''',
        '''    /* Guest GS is switched by the already-entered assembly leaf. */
    hrt_m10_enter_clone_child(context);
''',
        "pre-trampoline guest GS switch",
    )

    required = {
        "hrt_m10_enter_clone_child(context);": 1,
        "Guest GS is switched by the already-entered assembly leaf": 1,
        "(void)raw_set_gs(context->guest_gs);": 0,
        "m10_unblock_guest_trap_signals(": 2,
        "pthread_sigmask(SIG_UNBLOCK": 1,
        "SIGILL, SIGTRAP, SIGSEGV, SIGBUS, SIGABRT, SIGFPE": 1,
        "trap_mask_result != 0": 1,
        "case LINUX_SYS_CLONE:": 1,
        "case LINUX_SYS_CHDIR:": 1,
        "pthread_create(": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"clone-v4 marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
