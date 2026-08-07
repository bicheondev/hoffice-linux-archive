#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    static const char library_path[] =
        "LD_LIBRARY_PATH=/opt/hnc/hoffice11/Bin:"
        "/opt/hnc/hoffice11/Bin/qt/lib:"
        "/lib/x86_64-linux-gnu:"
        "/usr/lib/x86_64-linux-gnu:/lib64";
''',
        '''    static const char library_path[] =
        "LD_LIBRARY_PATH=/opt/hnc/hoffice11/Bin:"
        "/opt/hnc/hoffice11/Bin/qt/lib:"
        "/lib/x86_64-linux-gnu:"
        "/usr/lib/x86_64-linux-gnu:/lib64";
    static const char throw_probe[] =
        "LD_PRELOAD=/opt/hnc/hoffice11/Bin/libhrtthrowprobe.so";
''',
        "LD_PRELOAD declaration",
    )
    text = replace_once(
        text,
        '''        push_bytes(&cursor, floor, library_path, sizeof(library_path)),
        push_bytes(&cursor, floor, qt_platform, sizeof(qt_platform)),
''',
        '''        push_bytes(&cursor, floor, library_path, sizeof(library_path)),
        push_bytes(&cursor, floor, throw_probe, sizeof(throw_probe)),
        push_bytes(&cursor, floor, qt_platform, sizeof(qt_platform)),
''',
        "LD_PRELOAD environment vector",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
