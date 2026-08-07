#!/usr/bin/env python3
"""Extend the locked M9 throw probe with provider-object diagnostics.

The exact HWord failure is thrown from a COfficeCore construction path after
calling two virtual methods on the third constructor argument.  The first
method writes a string that is immediately sliced at byte three.  This wrapper
reuses the already-proven direct INT3 generator from commit 0a5f4b69 and adds a
second, parser-independent line containing:

* the preserved provider and constructor registers;
* the provider vtable, RTTI name and virtual slots 0x130/0x138; and
* the two std::string values produced by those virtual methods.

The original ``HRT M9 THROW INT3`` line is unchanged, so the existing capture
and attribution workflow remains fail-closed and backwards compatible.
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

LOCKED_COMMIT = "0a5f4b69f989a1fc9b59e692fbc5754cb2af0b54"
LOCKED_PATH = "runtime/m9/augment_int3_caller_probe.py"


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def run_locked_generator(source: Path, manifest: Path, output: Path,
                         exit_status: int) -> None:
    locked_source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout

    with tempfile.TemporaryDirectory(prefix="hrt-m9-int3-") as temporary:
        module_path = Path(temporary) / "locked_augment_int3_caller_probe.py"
        module_path.write_text(locked_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m9_locked_int3_probe", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked INT3 probe generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        previous_argv = sys.argv
        try:
            sys.argv = [
                str(module_path), str(source), str(manifest), str(output),
                "--exit-status", str(exit_status),
            ]
            module.main()
        finally:
            sys.argv = previous_argv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--exit-status", type=int, default=191)
    args = parser.parse_args()
    if not (1 <= args.exit_status <= 255):
        raise SystemExit("exit status must be in 1..255")

    with tempfile.TemporaryDirectory(prefix="hrt-m9-object-") as temporary:
        locked_output = Path(temporary) / "locked-output.c"
        run_locked_generator(
            args.source, args.manifest, locked_output, args.exit_status)
        text = locked_output.read_text(encoding="utf-8")

    anchor = f'''        raw_write_literal(buffer, written);
        raw_exit({args.exit_status});
'''
    replacement = f'''        raw_write_literal(buffer, written);

        /*
         * At the throw helper entry, RSP points at the return address.  The
         * caller's stack frame therefore begins eight bytes above it.  In the
         * exact COfficeCore path the two output std::string objects live at
         * caller-RSP+0x70 and caller-RSP+0x90.  RBX remains the provider object
         * whose virtual slots 0x130 and 0x138 populated those strings.
         */
        const uintptr_t caller_rsp =
            (uintptr_t)state->__rsp + sizeof(uint64_t);
        const uint64_t provider_object = state->__rbx;
        const uint64_t provider_vtable = provider_object != 0u
            ? *(const uint64_t *)(uintptr_t)provider_object : 0u;
        const uint64_t provider_offset_to_top = provider_vtable != 0u
            ? *((const uint64_t *)(uintptr_t)provider_vtable - 2) : 0u;
        const uint64_t provider_typeinfo = provider_vtable != 0u
            ? *((const uint64_t *)(uintptr_t)provider_vtable - 1) : 0u;
        const uint64_t provider_type_name = provider_typeinfo != 0u
            ? *((const uint64_t *)(uintptr_t)provider_typeinfo + 1) : 0u;
        const uint64_t provider_method_130 = provider_vtable != 0u
            ? *(const uint64_t *)(uintptr_t)(provider_vtable + 0x130u) : 0u;
        const uint64_t provider_method_138 = provider_vtable != 0u
            ? *(const uint64_t *)(uintptr_t)(provider_vtable + 0x138u) : 0u;

        const uint64_t first_data =
            *(const uint64_t *)(caller_rsp + 0x70u);
        const uint64_t first_length =
            *(const uint64_t *)(caller_rsp + 0x78u);
        const uint64_t second_data =
            *(const uint64_t *)(caller_rsp + 0x90u);
        const uint64_t second_length =
            *(const uint64_t *)(caller_rsp + 0x98u);
        const size_t first_text_limit = first_length <= 4096u
            ? (size_t)(first_length < 192u ? first_length : 192u) : 0u;
        const size_t second_text_limit = second_length <= 4096u
            ? (size_t)(second_length < 192u ? second_length : 192u) : 0u;

        char object_buffer[2048];
        size_t object_cursor = 0u;
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            "HRT M9 THROW OBJECT: rbx=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), state->__rbx);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " r12=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), state->__r12);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " r13=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), state->__r13);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " r14=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), state->__r14);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " r15=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), state->__r15);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " rbp=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), state->__rbp);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " vtable=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer),
            provider_vtable);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            " offset-to-top=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer),
            provider_offset_to_top);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " typeinfo=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer),
            provider_typeinfo);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            " type-name-pointer=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer),
            provider_type_name);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " type-name=");
        object_cursor = m9_probe_append_guest_string(
            object_buffer, object_cursor, sizeof(object_buffer),
            (const char *)(uintptr_t)provider_type_name, 160u);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            " method130=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer),
            provider_method_130);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            " method138=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer),
            provider_method_138);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            " first-data=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), first_data);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            " first-length=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), first_length);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " first=");
        object_cursor = m9_probe_append_guest_string(
            object_buffer, object_cursor, sizeof(object_buffer),
            (const char *)(uintptr_t)first_data, first_text_limit);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            " second-data=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), second_data);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer),
            " second-length=");
        object_cursor = m9_probe_append_hex(
            object_buffer, object_cursor, sizeof(object_buffer), second_length);
        object_cursor = m9_probe_append_literal(
            object_buffer, object_cursor, sizeof(object_buffer), " second=");
        object_cursor = m9_probe_append_guest_string(
            object_buffer, object_cursor, sizeof(object_buffer),
            (const char *)(uintptr_t)second_data, second_text_limit);
        object_cursor = m9_probe_append_char(
            object_buffer, object_cursor, sizeof(object_buffer), '\\n');
        const size_t object_written = object_cursor < sizeof(object_buffer)
            ? object_cursor : sizeof(object_buffer);
        raw_write_literal(object_buffer, object_written);
        raw_exit({args.exit_status});
'''
    text = replace_once(text, anchor, replacement,
                        "terminal throw-probe object diagnostics")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
