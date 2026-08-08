#!/usr/bin/env python3
"""Run the locked clone generator on every mature getcwd source shape.

The first clone generator at commit 4f699526 replaces the original root-only
``bridge_getcwd`` stub with guest-root-aware chdir/getcwd support.  Later bridge
compositions preserve the same function signature but may rewrite its body,
so this wrapper normalizes only that one balanced C function before invoking
the immutable generator.  It then changes the two emitted C++ ``static_assert``
tokens to C17 ``_Static_assert``.

Missing, duplicated, or malformed getcwd functions fail closed.  No other
source text is normalized.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "4f699526cf213a7c38df34faafeda1049bb06a19"
LOCKED_PATH = "runtime/m10/augment_clone_compat.py"
GETCWD_SIGNATURE = "static int64_t bridge_getcwd(char *buffer, size_t size) {"
GETCWD_STUB = """static int64_t bridge_getcwd(char *buffer, size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (size < 2u) return -LINUX_ERANGE;
    buffer[0] = '/';
    buffer[1] = '\\0';
    return 2;
}
"""


def balanced_function_end(text: str, opening_brace: int) -> int:
    depth = 0
    index = opening_brace
    state = "code"
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if char == '"':
                state = "string"
            elif char == "'":
                state = "character"
            elif char == "/" and following == "/":
                state = "line-comment"
                index += 1
            elif char == "/" and following == "*":
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
        elif state == "character":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif state == "line-comment":
            if char == "\n":
                state = "code"
        elif state == "block-comment":
            if char == "*" and following == "/":
                state = "code"
                index += 1
        index += 1
    raise SystemExit("bridge_getcwd function is not terminated")


def normalize_getcwd(source: Path, output: Path) -> None:
    text = source.read_text(encoding="utf-8")
    count = text.count(GETCWD_SIGNATURE)
    if count != 1:
        raise SystemExit(
            f"expected exactly one bridge_getcwd signature, found {count}")
    start = text.index(GETCWD_SIGNATURE)
    opening = start + GETCWD_SIGNATURE.rindex("{")
    end = balanced_function_end(text, opening)
    if text[end:end + 2] == "\r\n":
        end += 2
    elif text[end:end + 1] == "\n":
        end += 1
    normalized = text[:start] + GETCWD_STUB + text[end:]
    if normalized.count(GETCWD_STUB) != 1:
        raise SystemExit("normalized bridge_getcwd stub count is not one")
    output.write_text(normalized, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} SOURCE.c OUTPUT.c")
    source_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    locked_source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout

    with tempfile.TemporaryDirectory(prefix="hrt-m10-clone-") as temporary:
        temporary_root = Path(temporary)
        normalized_input = temporary_root / "normalized-input.c"
        normalize_getcwd(source_path, normalized_input)

        module_path = temporary_root / "locked_clone_generator.py"
        module_path.write_text(locked_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m10_locked_clone", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked clone generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous_argv = sys.argv
        try:
            sys.argv = [str(module_path), str(normalized_input), str(output_path)]
            module.main()
        finally:
            sys.argv = previous_argv

    text = output_path.read_text(encoding="utf-8")
    count = text.count("static_assert(")
    if count != 2:
        raise SystemExit(
            f"expected exactly two emitted static_assert tokens, found {count}")
    text = text.replace("static_assert(", "_Static_assert(")
    if text.count("_Static_assert(") < 2:
        raise SystemExit("C17 assertion rewrite did not complete")

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
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"clone marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")
    output_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
