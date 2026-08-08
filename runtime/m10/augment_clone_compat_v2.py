#!/usr/bin/env python3
"""Run the locked clone generator across mature getcwd source shapes.

The first clone generator at commit 4f699526 replaces the root-only
``bridge_getcwd`` function with a guest-root-aware chdir/getcwd pair.  Mature
bridge composition can change whitespace or the body of that function, so this
wrapper patches the locked generator's one named replacement operation: when
its exact old body is absent, the unique function is replaced by balanced C
function boundaries using the locked replacement text itself.

All other locked anchors remain strict.  The two emitted C++ ``static_assert``
tokens are then normalized to C17 ``_Static_assert``.
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


def replace_getcwd_function(text: str, replacement: str) -> str:
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
    result = text[:start] + replacement + text[end:]
    if result.count("static int64_t host_chdir_bridge(") != 1 or \
       result.count(GETCWD_SIGNATURE) != 1:
        raise SystemExit("parsed chdir/getcwd replacement did not close exactly")
    return result


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
        module_path = Path(temporary) / "locked_clone_generator.py"
        module_path.write_text(locked_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m10_locked_clone", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked clone generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        strict_replace = module.replace_once

        def compatible_replace(text: str, needle: str, replacement: str,
                               label: str) -> str:
            if label == "guest chdir and getcwd" and text.count(needle) == 0:
                return replace_getcwd_function(text, replacement)
            return strict_replace(text, needle, replacement, label)

        module.replace_once = compatible_replace
        previous_argv = sys.argv
        try:
            sys.argv = [str(module_path), str(source_path), str(output_path)]
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
