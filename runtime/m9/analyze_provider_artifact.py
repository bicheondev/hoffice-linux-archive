#!/usr/bin/env python3
"""Analyze the latest exact-HWord direct throw-probe artifact.

The artifact is intentionally self-contained: it has the terminal INT3 line,
the provider-object line, the SysV variadic argument line, executable mapping
records, the caller attribution JSON, and a locked copy of libHwordApp.so.
This analyzer turns those low-level records into a fail-closed diagnosis:

* the exact substring position and source size;
* which provider-returned string matches that source size;
* the provider RTTI and virtual slots 0x130/0x138;
* the ELF object/file offset owning each method and the throw caller; and
* whether the exception is a short culture/bootstrap string rather than a Qt
  or AppKit transport failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
from typing import Any


THROW_PATTERN = re.compile(
    r"HRT M9 THROW INT3: label=(.*?) symbol=(\S+) site=(0x[0-9a-f]+) "
    r"return=(0x[0-9a-f]+) rsp=(0x[0-9a-f]+) rdi=(0x[0-9a-f]+) "
    r"rsi=(0x[0-9a-f]+) format=(.*?) "
    r"stack0=(0x[0-9a-f]+) stack1=(0x[0-9a-f]+) "
    r"stack2=(0x[0-9a-f]+) stack3=(0x[0-9a-f]+) "
    r"stack4=(0x[0-9a-f]+) stack5=(0x[0-9a-f]+) "
    r"stack6=(0x[0-9a-f]+) stack7=(0x[0-9a-f]+)$"
)

PROVIDER_PATTERN = re.compile(
    r"HRT M9 THROW OBJECT: "
    r"rbx=(0x[0-9a-f]+) r12=(0x[0-9a-f]+) "
    r"r13=(0x[0-9a-f]+) r14=(0x[0-9a-f]+) "
    r"r15=(0x[0-9a-f]+) rbp=(0x[0-9a-f]+) "
    r"vtable=(0x[0-9a-f]+) offset-to-top=(0x[0-9a-f]+) "
    r"typeinfo=(0x[0-9a-f]+) "
    r"type-name-pointer=(0x[0-9a-f]+) type-name=(.*?) "
    r"method130=(0x[0-9a-f]+) method138=(0x[0-9a-f]+) "
    r"first-data=(0x[0-9a-f]+) first-length=(0x[0-9a-f]+) "
    r"first=(.*?) second-data=(0x[0-9a-f]+) "
    r"second-length=(0x[0-9a-f]+) second=(.*)$"
)

ARGS_PATTERN = re.compile(
    r"HRT M9 THROW ARGS: rdx=(0x[0-9a-f]+) rcx=(0x[0-9a-f]+) "
    r"r8=(0x[0-9a-f]+) r9=(0x[0-9a-f]+)$"
)

MAP_PATTERN = re.compile(
    r"HRT M9 MAP: start=(0x[0-9a-f]+) end=(0x[0-9a-f]+) "
    r"offset=(0x[0-9a-f]+) fd=(\d+) path=(.*)$"
)


def require_one(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise SystemExit(f"{label}: expected exactly one file, found {paths}")
    return paths[0]


def require_line(text: str, prefix: str, pattern: re.Pattern[str]) -> re.Match[str]:
    lines = [line for line in text.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise SystemExit(f"{prefix}: expected exactly one line, found {lines}")
    match = pattern.fullmatch(lines[0])
    if match is None:
        raise SystemExit(f"{prefix}: line did not match locked format: {lines[0]}")
    return match


def parse_maps(text: str) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = MAP_PATTERN.fullmatch(line)
        if match is None:
            continue
        mappings.append({
            "start": int(match.group(1), 16),
            "end": int(match.group(2), 16),
            "file_offset": int(match.group(3), 16),
            "fd": int(match.group(4)),
            "host_path": match.group(5),
        })
    if not mappings:
        raise SystemExit("no executable mapping records were present")
    return mappings


def owner_for(address: int, mappings: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [item for item in mappings
                  if item["start"] <= address < item["end"]]
    if not candidates:
        return None
    # Mappings may conservatively cover a larger reserved image span. Prefer
    # the narrowest range, then the latest start, to avoid attributing every
    # later DSO to the first large HWord reservation.
    owner = min(candidates,
                key=lambda item: (item["end"] - item["start"],
                                  -item["start"]))
    return {
        **owner,
        "address": address,
        "relative_address": address - owner["start"],
        "object_file_offset": (owner["file_offset"] +
                               address - owner["start"]),
    }


def elf_virtual_address(blob: bytes, file_offset: int) -> tuple[int, dict[str, int]]:
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", blob, 0)
    ident = header[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit("caller object is not little-endian ELF64")
    phoff, phentsize, phnum = header[5], header[9], header[10]
    if phentsize != 56:
        raise SystemExit(f"unexpected ELF64 program-header size: {phentsize}")
    for index in range(phnum):
        values = struct.unpack_from(
            "<IIQQQQQQ", blob, phoff + index * phentsize)
        p_type,p_flags,p_offset,p_vaddr,_paddr,p_filesz,p_memsz,p_align = values
        if p_type == 1 and p_offset <= file_offset < p_offset + p_filesz:
            return p_vaddr + file_offset - p_offset, {
                "index": index,
                "flags": p_flags,
                "file_offset": p_offset,
                "virtual_address": p_vaddr,
                "file_size": p_filesz,
                "memory_size": p_memsz,
                "alignment": p_align,
            }
    raise SystemExit(f"file offset 0x{file_offset:x} is outside PT_LOAD")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-run", required=True)
    args = parser.parse_args()

    root = args.input
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    attribution_path = require_one(
        list(root.rglob("caller-attribution.json")), "caller attribution")
    stderr_path = require_one(list(root.rglob("stderr.txt")), "stderr")
    caller_object = require_one(list(root.rglob("libHwordApp.so")),
                                "caller object")
    attribution = json.loads(attribution_path.read_text())
    stderr = stderr_path.read_text(errors="replace")

    if hashlib.sha256(caller_object.read_bytes()).hexdigest() != \
            attribution["caller_object_sha256"]:
        raise SystemExit("libHwordApp.so hash does not match caller attribution")

    throw = require_line(stderr, "HRT M9 THROW INT3:", THROW_PATTERN)
    provider_match = require_line(
        stderr, "HRT M9 THROW OBJECT:", PROVIDER_PATTERN)
    args_match = require_line(stderr, "HRT M9 THROW ARGS:", ARGS_PATTERN)
    mappings = parse_maps(stderr)

    provider_keys = [
        "rbx", "r12", "r13", "r14", "r15", "rbp", "vtable",
        "offset_to_top", "typeinfo", "type_name_pointer", "type_name",
        "method_130", "method_138", "first_data", "first_length_hex",
        "first_string", "second_data", "second_length_hex", "second_string",
    ]
    provider = dict(zip(provider_keys, provider_match.groups()))
    provider["first_length"] = int(provider.pop("first_length_hex"), 16)
    provider["second_length"] = int(provider.pop("second_length_hex"), 16)

    position = int(args_match.group(1), 16)
    source_size = int(args_match.group(2), 16)
    variadic = {
        "rdx_substring_position": position,
        "rcx_source_size": source_size,
        "r8": args_match.group(3),
        "r9": args_match.group(4),
    }

    matching_sources = []
    if provider["first_length"] == source_size:
        matching_sources.append("first_string")
    if provider["second_length"] == source_size:
        matching_sources.append("second_string")

    if position <= source_size:
        classification = "THROW_ARGUMENTS_DO_NOT_REPORT_OUT_OF_RANGE"
    elif matching_sources == ["first_string"]:
        classification = "FIRST_PROVIDER_STRING_TOO_SHORT_FOR_SUBSTR"
    elif matching_sources == ["second_string"]:
        classification = "SECOND_PROVIDER_STRING_TOO_SHORT_FOR_SUBSTR"
    elif len(matching_sources) == 2:
        classification = "BOTH_PROVIDER_STRINGS_MATCH_SHORT_SOURCE_SIZE"
    else:
        classification = "SHORT_SOURCE_NOT_IDENTIFIED_WITH_PROVIDER_OUTPUTS"

    method_owners = {
        "method_130": owner_for(int(provider["method_130"], 16), mappings),
        "method_138": owner_for(int(provider["method_138"], 16), mappings),
        "provider_vtable": owner_for(int(provider["vtable"], 16), mappings),
        "provider_typeinfo": owner_for(int(provider["typeinfo"], 16), mappings),
    }

    caller_blob = caller_object.read_bytes()
    caller_file_offset = int(attribution["caller_file_offset"])
    caller_virtual, caller_segment = elf_virtual_address(
        caller_blob, caller_file_offset)
    shutil.copy2(caller_object, output / "libHwordApp.so")

    result = {
        **attribution,
        "schema": 2,
        "milestone": "M9-provider-substr-diagnosis",
        "status": "PASS",
        "source_workflow_run": args.source_run,
        "classification": classification,
        "substring": {
            "position": position,
            "source_size": source_size,
            "matching_provider_sources": matching_sources,
            "format": throw.group(8),
            "format_function_name_pointer": throw.group(7),
        },
        "provider": provider,
        "provider_address_owners": method_owners,
        "caller_object_virtual_address": caller_virtual,
        "caller_load_segment": caller_segment,
        "executable_mapping_count": len(mappings),
    }

    (output / "diagnosis.json").write_text(
        json.dumps(result, indent=2) + "\n")
    (output / "caller-start.txt").write_text(
        str(max(0, caller_virtual - 768)) + "\n")
    (output / "caller-stop.txt").write_text(str(caller_virtual + 384) + "\n")
    (output / "diagnosis.md").write_text(
        "# Exact HWord provider/substr diagnosis\n\n"
        f"- Classification: `{classification}`\n"
        f"- `substr` position: `{position}`\n"
        f"- source size: `{source_size}`\n"
        f"- matched provider output: `{matching_sources}`\n"
        f"- provider RTTI name: `{provider['type_name']}`\n"
        f"- first string ({provider['first_length']} bytes): "
        f"`{provider['first_string']}`\n"
        f"- second string ({provider['second_length']} bytes): "
        f"`{provider['second_string']}`\n"
        f"- virtual slot `0x130`: `{provider['method_130']}`\n"
        f"- virtual slot `0x138`: `{provider['method_138']}`\n"
        f"- caller object: `{attribution['caller_guest_path']}`\n"
        f"- caller file offset: `0x{caller_file_offset:x}`\n"
        f"- caller virtual address: `0x{caller_virtual:x}`\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
