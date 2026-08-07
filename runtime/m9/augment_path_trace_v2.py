#!/usr/bin/env python3
"""Compatibility wrapper for the bounded M9 path tracer.

The mature bridge's readlink wrapper is rewritten by later syscall augmenters,
while open/stat/fstatat/access retain their locked shapes.  Readlink is not
needed to diagnose the HncBaseDraw font database bootstrap, so permit that one
optional anchor to be absent while keeping every relevant path hook
fail-closed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def main() -> int:
    module_path = Path(__file__).with_name("augment_path_trace.py")
    spec = importlib.util.spec_from_file_location("hrt_m9_path_trace_base", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit("unable to load augment_path_trace.py")
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
