#!/usr/bin/env python3
"""Patch one exact executable ELF virtual address with an INT3 byte.

This is intentionally stricter than a generic binary patcher.  It accepts only
64-bit little-endian x86-64 ET_DYN/ET_EXEC objects, requires the target virtual
address to lie in an executable PT_LOAD file range, optionally locks the
original byte prefix, and records before/after SHA-256 values plus the complete
probe signature in a JSON manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
PT_LOAD = 1
PF_X = 1
EM_X86_64 = 62
ET_EXEC = 2
ET_DYN = 3


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_int(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=Path)
    parser.add_argument("--virtual-address", required=True, type=parse_int)
    parser.add_argument("--label", required=True)
    parser.add_argument("--signature-length", type=int, default=24)
    parser.add_argument("--expected-prefix", default="")
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    if args.signature_length < 4 or args.signature_length > 128:
        raise SystemExit("signature length must be in 4..128")
    expected = bytes.fromhex(args.expected_prefix) if args.expected_prefix else b""

    blob = bytearray(args.elf.read_bytes())
    if len(blob) < ELF_HEADER.size:
        raise SystemExit("ELF is too small")
    header = ELF_HEADER.unpack_from(blob, 0)
    ident, elf_type, machine = header[0], header[1], header[2]
    program_offset, program_entry_size, program_count = (
        header[5], header[9], header[10]
    )
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit("expected an ELF64 little-endian object")
    if elf_type not in (ET_EXEC, ET_DYN) or machine != EM_X86_64:
        raise SystemExit("expected an x86-64 ET_EXEC or ET_DYN ELF")
    if program_entry_size != PROGRAM_HEADER.size:
        raise SystemExit("unexpected ELF program-header size")

    target = args.virtual_address
    file_offset: int | None = None
    segment: dict[str, int] | None = None
    for index in range(program_count):
        offset = program_offset + index * program_entry_size
        if offset + PROGRAM_HEADER.size > len(blob):
            raise SystemExit("truncated program-header table")
        values = PROGRAM_HEADER.unpack_from(blob, offset)
        p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz, p_memsz, p_align = values
        if p_type != PT_LOAD or (p_flags & PF_X) == 0:
            continue
        if p_vaddr <= target < p_vaddr + p_filesz:
            file_offset = p_offset + (target - p_vaddr)
            segment = {
                "index": index,
                "flags": p_flags,
                "file_offset": p_offset,
                "virtual_address": p_vaddr,
                "file_size": p_filesz,
                "memory_size": p_memsz,
                "alignment": p_align,
            }
            break
    if file_offset is None or segment is None:
        raise SystemExit("target is not inside an executable PT_LOAD file range")
    if file_offset + args.signature_length > len(blob):
        raise SystemExit("probe signature extends beyond the ELF file")

    original = bytes(blob[file_offset:file_offset + args.signature_length])
    if original[0] == 0xCC:
        raise SystemExit("target is already an INT3 instruction")
    if expected and not original.startswith(expected):
        raise SystemExit(
            f"expected prefix {expected.hex()}, found {original[:len(expected)].hex()}"
        )

    before = digest(bytes(blob))
    blob[file_offset] = 0xCC
    patched = bytes(blob[file_offset:file_offset + args.signature_length])
    after = digest(bytes(blob))
    args.elf.write_bytes(blob)

    manifest = {
        "schema": 1,
        "kind": "exact-address-int3",
        "label": args.label,
        "path": str(args.elf),
        "elf_type": elf_type,
        "machine": machine,
        "virtual_address": target,
        "file_offset": file_offset,
        "segment": segment,
        "signature_length": args.signature_length,
        "original_bytes_hex": original.hex(),
        "patched_bytes_hex": patched.hex(),
        "sha256_before": before,
        "sha256_after": after,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
