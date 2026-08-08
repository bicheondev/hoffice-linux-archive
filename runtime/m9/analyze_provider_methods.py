#!/usr/bin/env python3
"""Resolve HWord provider vtable slots to exact ELF call targets.

Input is the durable provider/substr diagnosis and an extracted exact guest
root.  For slots 0x130 and 0x138, the tool verifies the guest object against
``.hrt-prepatched-v1``, converts the runtime mapping/file offset to an ELF
virtual address, and emits deterministic disassembly ranges.  The workflow can
then use ordinary readelf/objdump to identify nearby symbols and implementation
clues without modifying the package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any


METHODS = ("method_130", "method_138")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guest_path(host_path: str) -> str:
    candidates = []
    for marker in ("/opt/", "/lib/", "/lib64/", "/usr/", "/etc/"):
        position = host_path.find(marker)
        if position >= 0:
            candidates.append((position, host_path[position:]))
    if not candidates:
        raise SystemExit(f"cannot derive guest path from {host_path}")
    return min(candidates, key=lambda item: item[0])[1]


def virtual_address(blob: bytes, file_offset: int) -> tuple[int, dict[str, int]]:
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", blob, 0)
    ident = header[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit("provider object is not little-endian ELF64")
    phoff, phentsize, phnum = header[5], header[9], header[10]
    if phentsize != 56:
        raise SystemExit(f"unexpected program-header size {phentsize}")
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
    raise SystemExit(f"file offset 0x{file_offset:x} is not in PT_LOAD")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--diagnosis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    diagnosis = json.loads(args.diagnosis.read_text())
    if diagnosis.get("status") != "PASS":
        raise SystemExit("provider diagnosis is not PASS")
    owners = diagnosis.get("provider_address_owners")
    if not isinstance(owners, dict):
        raise SystemExit("provider owner table is absent")

    prepatch = json.loads((root / ".hrt-prepatched-v1").read_text())
    locks = {item["path"]: item for item in prepatch["objects"]}
    objects: dict[str, dict[str, Any]] = {}
    methods = {}

    for key in METHODS:
        owner = owners.get(key)
        if not isinstance(owner, dict):
            raise SystemExit(f"{key}: no owner mapping")
        path = guest_path(str(owner["host_path"]))
        image = root / path.lstrip("/")
        if not image.is_file():
            raise SystemExit(f"{key}: missing object {path}")
        lock = locks.get(path)
        if lock is None:
            raise SystemExit(f"{key}: {path} is absent from prepatch lock")
        actual = sha256(image)
        if actual != lock["sha256_after"]:
            raise SystemExit(
                f"{key}: hash mismatch {actual} != {lock['sha256_after']}")
        file_offset = int(owner["object_file_offset"])
        address, segment = virtual_address(image.read_bytes(), file_offset)
        object_key = hashlib.sha256(path.encode()).hexdigest()[:12]
        if object_key not in objects:
            destination = output / f"object-{object_key}-{image.name}"
            destination.write_bytes(image.read_bytes())
            objects[object_key] = {
                "guest_path": path,
                "copied_path": str(destination),
                "sha256": actual,
                "prepatch_record": lock,
            }
        methods[key] = {
            "slot": int(diagnosis["provider"][key.replace("method_", "method_")]
                        and (0x130 if key == "method_130" else 0x138)),
            "runtime_address": diagnosis["provider"][key],
            "guest_path": path,
            "object_key": object_key,
            "file_offset": file_offset,
            "virtual_address": address,
            "load_segment": segment,
            "disassembly_start": max(0, address - 384),
            "disassembly_stop": address + 768,
        }

    result = {
        "schema": 1,
        "milestone": "M9-provider-methods",
        "status": "PASS",
        "source_workflow_run": diagnosis.get("source_workflow_run"),
        "provider_type": diagnosis["provider"].get("type_name"),
        "provider_vtable": diagnosis["provider"].get("vtable"),
        "substring": diagnosis.get("substring"),
        "objects": objects,
        "methods": methods,
    }
    (output / "provider-methods.json").write_text(
        json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
