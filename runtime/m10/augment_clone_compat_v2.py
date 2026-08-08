#!/usr/bin/env python3
"""Run the locked clone generator and normalize C17 static assertions.

The first clone generator at commit 4f699526 uses C++ spelling for two
compile-time assertions inside emitted C.  This wrapper preserves every bridge
edit and replaces only those exact tokens with C17 ``_Static_assert``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "4f699526cf213a7c38df34faafeda1049bb06a19"
LOCKED_PATH = "runtime/m10/augment_clone_compat.py"


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
    output_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
