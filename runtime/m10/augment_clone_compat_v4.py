#!/usr/bin/env python3
"""Move clone-child GS switching from C into the assembly trampoline.

The v2 generator establishes a real pthread-backed Linux clone context, but its
child callback changed GS before making the first call to the Mach-O assembly
symbol.  Under Rosetta that call can still pass through host runtime machinery
that expects the pthread's host TLS, so the child never entered the trampoline.

This wrapper runs v2 unchanged, removes exactly the one pre-call ``raw_set_gs``
operation, and requires the trampoline to own the guest TLS switch.  The
trampoline records the Linux TLS argument in the per-thread context before the
first guest instruction, so later signal handlers retain the same state model.
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
