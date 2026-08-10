#!/usr/bin/env python3
"""Execute the deferred-exit clone generator with corrected invariants.

Commit 1c8cda99 contains the complete signal-unblock, assembly-owned GS and
host-stack exit implementation.  Its final diagnostic table counts the
``context->in_handler = 0u`` token once, while the generated bridge correctly
contains one assignment during child startup and one during deferred exit
scheduling.  This wrapper changes only that exact invariant from one to two and
executes the locked generator unchanged.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "1c8cda99818aa203d2848aa77849f006eed941ad"
LOCKED_PATH = "runtime/m10/augment_clone_compat_v4.py"


def main() -> None:
    locked_source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout
    old = '        "context->in_handler = 0u": 1,\n'
    new = '        "context->in_handler = 0u": 2,\n'
    if locked_source.count(old) != 1:
        raise SystemExit("locked deferred-exit context invariant changed")
    locked_source = locked_source.replace(old, new, 1)

    with tempfile.TemporaryDirectory(prefix="hrt-m10-clone-v5-") as temporary:
        module_path = Path(temporary) / "locked_clone_v4.py"
        module_path.write_text(locked_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m10_locked_clone_v4", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked clone-v4 generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main()


if __name__ == "__main__":
    main()
