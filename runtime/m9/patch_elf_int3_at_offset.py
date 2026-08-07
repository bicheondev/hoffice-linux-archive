#!/usr/bin/env python3
"""Patch one exact file-backed executable byte in an ELF64 object with INT3.

The caller supplies a file offset already derived from a locked runtime mapping.
This tool independently verifies that the offset belongs to an executable
PT_LOAD segment, records a bounded instruction signature, and fails closed if
the site is already patched or malformed.
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


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=Path)
    parser.add_argument("--file-offset", required=True, type=lambda v: int(v, 0))
    parser.add_argument("--label", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--signature-length", type=int, default=24)
    args = parser.parse_args()

    blob = bytearray(args.elf.read_bytes())
    before = bytes(blob)
    header = ELF_HEADER.unpack_from(blob, 0)
    ident = header[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit("only little-endian ELF64 is supported")
    machine = header[2]
    phoff, phentsize, phnum = header[5], header[9], header[10]
    if machine != 62 or phentsize != PROGRAM_HEADER.size:
        raise SystemExit("unexpected ELF64 x86-64 header")

    offset = args.file_offset
    if offset < 0 or offset >= len(blob):
        raise SystemExit("file offset is outside the ELF object")
    segment = None
    virtual_address = None
    for index in range(phnum):
        values = PROGRAM_HEADER.unpack_from(blob, phoff + index * phentsize)
        p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz, p_memsz, p_align = values
        if p_type == PT_LOAD and p_offset <= offset < p_offset + p_filesz:
            if (p_flags & PF_X) == 0:
                raise SystemExit("selected offset is not in an executable PT_LOAD")
            virtual_address = p_vaddr + offset - p_offset
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
    if segment is None or virtual_address is None:
        raise SystemExit("selected offset is not file-backed by PT_LOAD")

    length = args.signature_length
    if length < 4 or length > 64 or offset + length > len(blob):
        raise SystemExit("invalid signature length")
    original = bytes(blob[offset:offset + length])
    if original[0] == 0xCC:
        raise SystemExit("selected site already begins with INT3")
    blob[offset] = 0xCC
    after = bytes(blob)
    args.elf.write_bytes(after)

    manifest = {
        "schema": 1,
        "elf": str(args.elf),
        "label": args.label,
        "file_offset": offset,
        "virtual_address": virtual_address,
        "segment": segment,
        "signature_length": length,
        "original_bytes_hex": original.hex(),
        "patched_bytes_hex": bytes(blob[offset:offset + length]).hex(),
        "sha256_before": digest(before),
        "sha256_after": digest(after),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
