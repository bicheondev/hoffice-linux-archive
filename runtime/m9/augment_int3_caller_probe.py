#!/usr/bin/env python3
"""Add SysV variadic arguments to the proven M9 provider-object probe.

Commit ``9aca02ec`` already records the exact provider object, vtable, RTTI and
the two strings returned immediately before the failing substring operation.
This stable wrapper reuses that locked generator and appends a separate line
for RDX/RCX/R8/R9.  For ``std::__throw_out_of_range_fmt`` those registers hold
the requested substring position and source length after the leading ``%s``
argument in RSI.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "9aca02ecadca412dfe5db725d0ca6e42811ebfdc"
LOCKED_PATH = "runtime/m9/augment_int3_caller_probe.py"


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def run_locked(source: Path, manifest: Path, output: Path,
               exit_status: int) -> None:
    locked_source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="hrt-m9-args-") as temporary:
        module_path = Path(temporary) / "locked_probe.py"
        module_path.write_text(locked_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m9_locked_provider_probe", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked provider probe")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous = sys.argv
        try:
            sys.argv = [
                str(module_path), str(source), str(manifest), str(output),
                "--exit-status", str(exit_status),
            ]
            module.main()
        finally:
            sys.argv = previous


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--exit-status", type=int, default=191)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="hrt-m9-args-output-") as temporary:
        locked_output = Path(temporary) / "locked-output.c"
        run_locked(args.source, args.manifest, locked_output,
                   args.exit_status)
        text = locked_output.read_text(encoding="utf-8")

    anchor = f'''        raw_write_literal(object_buffer, object_written);
        raw_exit({args.exit_status});
'''
    replacement = f'''        raw_write_literal(object_buffer, object_written);

        char argument_buffer[512];
        size_t argument_cursor = 0u;
        argument_cursor = m9_probe_append_literal(
            argument_buffer, argument_cursor, sizeof(argument_buffer),
            "HRT M9 THROW ARGS: rdx=");
        argument_cursor = m9_probe_append_hex(
            argument_buffer, argument_cursor, sizeof(argument_buffer),
            state->__rdx);
        argument_cursor = m9_probe_append_literal(
            argument_buffer, argument_cursor, sizeof(argument_buffer),
            " rcx=");
        argument_cursor = m9_probe_append_hex(
            argument_buffer, argument_cursor, sizeof(argument_buffer),
            state->__rcx);
        argument_cursor = m9_probe_append_literal(
            argument_buffer, argument_cursor, sizeof(argument_buffer),
            " r8=");
        argument_cursor = m9_probe_append_hex(
            argument_buffer, argument_cursor, sizeof(argument_buffer),
            state->__r8);
        argument_cursor = m9_probe_append_literal(
            argument_buffer, argument_cursor, sizeof(argument_buffer),
            " r9=");
        argument_cursor = m9_probe_append_hex(
            argument_buffer, argument_cursor, sizeof(argument_buffer),
            state->__r9);
        argument_cursor = m9_probe_append_char(
            argument_buffer, argument_cursor, sizeof(argument_buffer), '\\n');
        const size_t argument_written =
            argument_cursor < sizeof(argument_buffer)
                ? argument_cursor : sizeof(argument_buffer);
        raw_write_literal(argument_buffer, argument_written);
        raw_exit({args.exit_status});
'''
    text = replace_once(text, anchor, replacement,
                        "terminal provider-probe argument diagnostics")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
