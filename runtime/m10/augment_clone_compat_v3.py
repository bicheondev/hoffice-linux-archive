#!/usr/bin/env python3
"""Apply the M10 clone bridge to every mature getcwd source shape.

The locked clone generator replaces the original root-only ``bridge_getcwd``
stub with a guest-root-aware chdir/getcwd pair.  Later bridge compositions can
rewrite that function without changing its signature, so matching the entire
old function body is unnecessarily brittle.  This compatibility wrapper:

1. finds the one exact ``bridge_getcwd`` function;
2. parses its balanced C braces while respecting strings and comments;
3. normalizes only that function to the locked stub; and
4. runs the compile-safe v2 clone generator unchanged.

The generated output still contains the full real chdir/getcwd implementation
from the locked clone generator.  Missing, duplicated, or malformed functions
fail closed before any output is written.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

SIGNATURE = "static int64_t bridge_getcwd(char *buffer, size_t size) {"
LOCKED_STUB = """static int64_t bridge_getcwd(char *buffer, size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (size < 2u) return -LINUX_ERANGE;
    buffer[0] = '/';
    buffer[1] = '\\0';
    return 2;
}
"""


def function_end(text: str, opening_brace: int) -> int:
    depth = 0
    index = opening_brace
    state = "code"
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if state == "code":
            if char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == "/" and next_char == "/":
                state = "line-comment"
                index += 1
            elif char == "/" and next_char == "*":
                state = "block-comment"
                index += 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
                if depth < 0:
                    raise SystemExit("bridge_getcwd has an unmatched closing brace")
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "char":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif state == "line-comment":
            if char == "\n":
                state = "code"
        elif state == "block-comment":
            if char == "*" and next_char == "/":
                state = "code"
                index += 1
        index += 1
    raise SystemExit("bridge_getcwd function is not terminated")


def normalize_getcwd(source: Path, output: Path) -> None:
    text = source.read_text(encoding="utf-8")
    count = text.count(SIGNATURE)
    if count != 1:
        raise SystemExit(
            f"expected exactly one bridge_getcwd signature, found {count}")
    start = text.index(SIGNATURE)
    opening = start + SIGNATURE.rindex("{")
    end = function_end(text, opening)

    suffix = text[end:]
    if suffix.startswith("\r\n"):
        end += 2
    elif suffix.startswith("\n"):
        end += 1

    normalized = text[:start] + LOCKED_STUB + text[end:]
    if normalized.count(LOCKED_STUB) != 1:
        raise SystemExit("normalized bridge_getcwd stub count is not one")
    output.write_text(normalized, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="hrt-m10-clone-v3-") as temporary:
        normalized = Path(temporary) / "normalized-input.c"
        normalize_getcwd(args.source, normalized)
        subprocess.run(
            [
                sys.executable,
                "runtime/m10/augment_clone_compat_v2.py",
                str(normalized),
                str(args.output),
            ],
            check=True,
        )

    generated = args.output.read_text(encoding="utf-8")
    required = {
        "case LINUX_SYS_CLONE:": 1,
        "case LINUX_SYS_CHDIR:": 1,
        "static int64_t host_chdir_bridge(": 1,
        "static int64_t bridge_getcwd(": 1,
        "pthread_create(": 1,
        "rdgsbase": 1,
        "HRT M10 CLONE:": 1,
    }
    for marker, expected in required.items():
        actual = generated.count(marker)
        if actual != expected:
            raise SystemExit(
                f"generated clone marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")


if __name__ == "__main__":
    main()
