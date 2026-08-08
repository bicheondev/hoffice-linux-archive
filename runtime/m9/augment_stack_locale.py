#!/usr/bin/env python3
"""Inject the Linux locale/user environment expected by HWord.

The clean-room initial stack intentionally started with a tiny environment.
That was sufficient for ld-linux, glibc, Qt and the AppKit QPA, but HWord's
bootstrap provider later returns a culture string and immediately takes
``substr(3)``.  A process without LANG/LC_ALL commonly resolves to the one-byte
``C`` locale, which is not a valid language_region identifier for that code.

This augmenter runs after ``augment_stack_hrtappkit.py`` and adds a complete,
explicit environment without changing argv, auxv or the QPA variables.  Both
the declaration and environment-vector anchors are unique and fail closed.
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
    if "LANG=ko_KR.UTF-8" in text:
        raise SystemExit("Korean locale environment is already present")

    declaration_anchor = '''    static const char library_path[] =
        "LD_LIBRARY_PATH=/opt/hnc/hoffice11/Bin:"
        "/opt/hnc/hoffice11/Bin/qt/lib:"
        "/lib/x86_64-linux-gnu:"
        "/usr/lib/x86_64-linux-gnu:/lib64";
'''
    declarations = declaration_anchor + '''    static const char locale_lang[] = "LANG=ko_KR.UTF-8";
    static const char locale_all[] = "LC_ALL=ko_KR.UTF-8";
    static const char locale_messages[] = "LC_MESSAGES=ko_KR.UTF-8";
    static const char locale_language[] = "LANGUAGE=ko_KR:ko:en";
    static const char user_home[] = "HOME=/home/hrt";
    static const char user_name[] = "USER=hrt";
    static const char log_name[] = "LOGNAME=hrt";
    static const char xdg_data[] =
        "XDG_DATA_DIRS=/opt/hnc/hoffice11/share:"
        "/usr/local/share:/usr/share";
'''
    text = replace_once(text, declaration_anchor, declarations,
                        "HWord environment declarations")

    vector_anchor = '''        push_bytes(&cursor, floor, library_path, sizeof(library_path)),
        push_bytes(&cursor, floor, qt_platform, sizeof(qt_platform)),
'''
    vector = '''        push_bytes(&cursor, floor, library_path, sizeof(library_path)),
        push_bytes(&cursor, floor, locale_lang, sizeof(locale_lang)),
        push_bytes(&cursor, floor, locale_all, sizeof(locale_all)),
        push_bytes(&cursor, floor, locale_messages, sizeof(locale_messages)),
        push_bytes(&cursor, floor, locale_language, sizeof(locale_language)),
        push_bytes(&cursor, floor, user_home, sizeof(user_home)),
        push_bytes(&cursor, floor, user_name, sizeof(user_name)),
        push_bytes(&cursor, floor, log_name, sizeof(log_name)),
        push_bytes(&cursor, floor, xdg_data, sizeof(xdg_data)),
        push_bytes(&cursor, floor, qt_platform, sizeof(qt_platform)),
'''
    text = replace_once(text, vector_anchor, vector,
                        "HWord environment vector")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
