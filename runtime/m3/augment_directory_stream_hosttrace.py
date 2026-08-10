#!/usr/bin/env python3
"""Use host write for directory-stream proof markers.

The stream converter is inside an explicit host GS section while readdir is
active.  This tiny fail-closed augmentation keeps the diagnostic write in
that same context instead of invoking the guest-side raw trace helper.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8")
    old = "            raw_write_literal(marker, sizeof(marker) - 1u);\n"
    new = (
        "            (void)write(STDERR_FILENO, marker, "
        "sizeof(marker) - 1u);\n"
    )
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"directory marker: expected one raw-write anchor, found {count}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
