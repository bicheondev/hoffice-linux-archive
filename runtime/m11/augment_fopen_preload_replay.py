#!/usr/bin/env python3
"""Install the scoped HWord fopen interposer in a generated replay script.

The full-product replay generator intentionally knows nothing about optional
compatibility experiments.  This small postprocessor adds one guest-side
library and ``/etc/ld.so.preload`` entry at the exact point where the custom
QPA plugin has already been installed and made executable.

The edit is fail closed: the source anchor must occur exactly once, pre-existing
preload markers are rejected, and the generated script is audited before it is
written.  No guest ELF is modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path


INSTALL_MARKER = "HRT M11 PRELOAD V3 INSTALL:"
LIBRARY_BASENAME = "libhrt_hword_fopen.so"
GUEST_LIBRARY = "/opt/hrt/libhrt_hword_fopen.so"
GUEST_CONFIG = "/etc/ld.so.preload"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if INSTALL_MARKER in text or GUEST_LIBRARY in text:
        raise SystemExit("guest fopen preload installation is already present")

    anchor = 'chmod 0755 "$root$PLUGIN_GUEST"\n'
    count = text.count(anchor)
    if count != 1:
        raise SystemExit(
            f"preload install anchor: expected one, found {count}")

    insertion = anchor + r'''install -D -m 0755 build/input/preload/libhrt_hword_fopen.so \
    "$root/opt/hrt/libhrt_hword_fopen.so"
mkdir -p "$root/etc"
printf '%s\n' '/opt/hrt/libhrt_hword_fopen.so' >"$root/etc/ld.so.preload"
test -s "$root/etc/ld.so.preload"
test -x "$root/opt/hrt/libhrt_hword_fopen.so"
printf 'HRT M11 PRELOAD V3 INSTALL: library=%s config=%s\n' \
    "$root/opt/hrt/libhrt_hword_fopen.so" "$root/etc/ld.so.preload"
'''
    generated = text.replace(anchor, insertion, 1)

    required = {
        INSTALL_MARKER: 1,
        LIBRARY_BASENAME: 4,
        GUEST_LIBRARY: 4,
        GUEST_CONFIG: 2,
        "install -D -m 0755": 1,
        'printf \'%s\\n\' \'/opt/hrt/libhrt_hword_fopen.so\'': 1,
    }
    for marker, expected in required.items():
        actual = generated.count(marker)
        if actual != expected:
            raise SystemExit(
                f"preload generated marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generated, encoding="utf-8")
    args.output.chmod(0o755)


if __name__ == "__main__":
    main()
