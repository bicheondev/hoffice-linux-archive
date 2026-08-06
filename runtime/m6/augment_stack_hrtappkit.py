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
        'static const char milestone[] = "HRT_MILESTONE=M5_OFFSCREEN";',
        'static const char milestone[] = "HRT_MILESTONE=M6_HRTAPPKIT";',
        "milestone",
    )
    text = replace_once(
        text,
        'static const char qt_platform[] = "QT_QPA_PLATFORM=offscreen";',
        'static const char qt_platform[] = "QT_QPA_PLATFORM=hrtappkit";',
        "Qt platform",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
