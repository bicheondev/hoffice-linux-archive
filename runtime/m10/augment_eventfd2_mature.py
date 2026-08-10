#!/usr/bin/env python3
"""Compile-safe wrapper for the mature HWord eventfd2 bridge.

The first mature generator at commit b824a479 correctly integrated eventfd2
with directory and epoll close ownership, but its table was inserted before the
already-generated pipe2 helper definition.  C17 therefore requires a matching
static forward declaration.  This wrapper runs the immutable generator and
adds exactly that declaration; no eventfd behavior changes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "b824a479a8eda6d6ccdb8ab93a724723e722cdc9"
LOCKED_PATH = "runtime/m10/augment_eventfd2_mature.py"


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def run_locked(source: Path, output: Path) -> None:
    locked_source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="hrt-m10-eventfd-") as temporary:
        module_path = Path(temporary) / "locked_eventfd2_mature.py"
        module_path.write_text(locked_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m10_locked_eventfd2", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked mature eventfd generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous_argv = sys.argv
        try:
            sys.argv = [str(module_path), str(source), str(output)]
            module.main()
        finally:
            sys.argv = previous_argv


def add_forward_declaration(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    declaration = (
        "static int set_pipe_descriptor_flags(int fd, "
        "uint64_t linux_flags);\n\n"
    )
    text = replace_once(
        text,
        "#define M10_MAX_EVENTFDS 64u\n",
        declaration + "#define M10_MAX_EVENTFDS 64u\n",
        "pipe flag helper forward declaration",
    )
    if text.count(declaration.strip()) != 1:
        raise SystemExit("pipe flag helper declaration count mismatch")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} SOURCE.c OUTPUT.c")
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    run_locked(source, output)
    add_forward_declaration(output)


if __name__ == "__main__":
    main()
