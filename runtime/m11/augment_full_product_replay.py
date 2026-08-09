#!/usr/bin/env python3
"""Create a diagnostic replay that restores the complete exact HOffice tree.

The credible-editor frontier creates ``hanul::DocumentTabImpl`` but never adds
an ``hword::HwordAppView`` page.  Startup traces show hundreds of missing HOffice
font, TTF, resource and shared-data paths.  The curated bootstrap rootfs was
sufficient for the main window, but it has not proved product-payload closure
for document creation.

This transform keeps the audited replay unchanged and inserts one exact,
reversible experiment after the existing minimal resource restore: every entry
under ``/opt/hnc/hoffice11`` from the immutable package data archive is
re-applied to the mounted guest.  The existing culture patch and custom QPA are
installed afterwards, so their audited bytes still win.  A path manifest,
entry count and extracted byte count are preserved in the proof artifact.
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
    if "full-product-payload-paths.txt" in text:
        raise SystemExit("full product payload replay is already present")

    anchor = '''    ./opt/hnc/hoffice11/Bin/qt/translations/qt_en.qm \\
    ./opt/hnc/hoffice11/Bin/qt/translations/qt_ko.qm
printf '%s  %s\\n' \\
'''
    replacement = '''    ./opt/hnc/hoffice11/Bin/qt/translations/qt_en.qm \\
    ./opt/hnc/hoffice11/Bin/qt/translations/qt_ko.qm

# M11 diagnostic closure gate: restore the complete immutable product tree.
tar -tf "build/input/deb/$data_member" \\
    | LC_ALL=C grep -E '^\\./opt/hnc/hoffice11(/|$)' \\
    | LC_ALL=C sort -u \\
    >build/proof/full-product-payload-paths.txt
test -s build/proof/full-product-payload-paths.txt
tar -xf "build/input/deb/$data_member" -C "$root" \\
    -T build/proof/full-product-payload-paths.txt
find "$root/opt/hnc/hoffice11" -type f -print0 \\
    | python3 -c 'import os,sys; data=sys.stdin.buffer.read().split(b"\\0"); paths=[p for p in data if p]; print(sum(os.stat(p).st_size for p in paths))' \\
    >build/proof/full-product-payload-bytes.txt
wc -l <build/proof/full-product-payload-paths.txt \\
    | tr -d ' ' >build/proof/full-product-payload-count.txt
printf 'HRT M11 PAYLOAD: entries=%s bytes=%s\\n' \\
    "$(cat build/proof/full-product-payload-count.txt)" \\
    "$(cat build/proof/full-product-payload-bytes.txt)"

printf '%s  %s\\n' \\
'''
    text = replace_once(text, anchor, replacement,
                        "complete product payload insertion")

    required = {
        "full-product-payload-paths.txt": 4,
        "full-product-payload-bytes.txt": 2,
        "full-product-payload-count.txt": 2,
        "HRT M11 PAYLOAD:": 1,
        "^\\./opt/hnc/hoffice11(/|$)": 1,
        "patch_hword_utility_culture_redirect.py": 1,
        "libqhrtappkit.so.xz": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"full-payload marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    args.output.chmod(0o755)


if __name__ == "__main__":
    main()
