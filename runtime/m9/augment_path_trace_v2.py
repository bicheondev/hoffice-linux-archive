#!/usr/bin/env python3
"""Compatibility launcher for the bounded M9 path tracer.

The original tracer is loaded from its immutable source commit.  Later mature
bridge augmenters rewrote the readlink wrapper, so that one optional hook may
be absent; the font-relevant open/stat/fstatat/access hooks remain strictly
shape-checked.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "988d710703f11747f1cd50e3dd7da2f63e25d1eb"
LOCKED_PATH = "runtime/m9/augment_path_trace.py"


def main() -> int:
    source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout

    with tempfile.TemporaryDirectory(prefix="hrt-m9-path-") as temporary:
        module_path = Path(temporary) / "locked_augment_path_trace.py"
        module_path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m9_path_trace_locked", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked path tracer")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        strict_replace = module.replace_once

        def compatible_replace(text: str, needle: str, replacement: str,
                               label: str) -> str:
            count = text.count(needle)
            if label == "readlink path trace" and count == 0:
                return text
            return strict_replace(text, needle, replacement, label)

        module.replace_once = compatible_replace
        module.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
