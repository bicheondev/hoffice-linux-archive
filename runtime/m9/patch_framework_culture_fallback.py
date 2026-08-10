#!/usr/bin/env python3
"""Patch Hnc::Framework::GetCulture() to use its built-in en-US fallback.

The exact HOffice 11.20.0.1520 HWord guest installs a non-null framework site,
but that site's culture provider is not initialized in the clean-room macOS
runtime yet. ``Framework::GetCulture`` therefore returns an empty
``CHncStringW`` and HWord immediately performs ``substr(3)``, raising
``std::out_of_range``.

The original function already contains a safe no-site fallback that constructs
``L\"en-US\"``. This patch changes only the conditional branch after
``GetSite()`` from ``JE fallback`` to ``JMP fallback``. It does not synthesize
new code, change the ABI, or alter any other method.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")
SYMBOL = struct.Struct("<IBBHQQ")
PT_LOAD = 1
SHT_DYNSYM = 11
STT_FUNC = 2
TARGET_SYMBOL = "_ZNK3Hnc9Framework10GetCultureEv"
EXPECTED_FUNCTION_PREFIX = bytes.fromhex(
    "554889fd4889f7534889f34883ec08488b06ff50404885c07426"
)
ORIGINAL_BRANCH = bytes.fromhex("7426")
PATCHED_BRANCH = bytes.fromhex("eb26")
FALLBACK_UTF16 = "en-US".encode("utf-16le") + b"\0\0"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def c_string(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", errors="replace")


def virtual_to_file(programs: list[tuple[int, ...]], address: int) -> int:
    for values in programs:
        p_type, _flags, p_offset, p_vaddr, _paddr, p_filesz, _p_memsz, _align = values
        if p_type == PT_LOAD and p_vaddr <= address < p_vaddr + p_filesz:
            return p_offset + address - p_vaddr
    raise SystemExit(f"virtual address 0x{address:x} is not file-backed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    blob = bytearray(args.elf.read_bytes())
    before = bytes(blob)
    before_sha = sha256(before)
    if before_sha != args.expected_sha256:
        raise SystemExit(
            f"unexpected input SHA-256: {before_sha} != {args.expected_sha256}"
        )

    header = ELF_HEADER.unpack_from(blob, 0)
    ident = header[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit("only little-endian ELF64 is supported")
    (
        _ident, _elf_type, machine, _version, _entry,
        phoff, shoff, _flags, _ehsize, phentsize, phnum,
        shentsize, shnum, _shstrndx,
    ) = header
    if machine != 62 or phentsize != PROGRAM_HEADER.size or \
            shentsize != SECTION_HEADER.size:
        raise SystemExit("unexpected ELF64 x86-64 layout")

    programs = [PROGRAM_HEADER.unpack_from(blob, phoff + i * phentsize)
                for i in range(phnum)]
    sections = [SECTION_HEADER.unpack_from(blob, shoff + i * shentsize)
                for i in range(shnum)]

    matches: list[tuple[int, int]] = []
    for section in sections:
        (_name, section_type, _flags, _address, section_offset, section_size,
         link, _info, _alignment, entry_size) = section
        if section_type != SHT_DYNSYM or entry_size != SYMBOL.size or \
                link >= len(sections):
            continue
        strings_section = sections[link]
        strings_offset = strings_section[4]
        strings_size = strings_section[5]
        strings = bytes(blob[strings_offset:strings_offset + strings_size])
        for index in range(section_size // entry_size):
            symbol_offset = section_offset + index * entry_size
            name_offset, info, _other, _shndx, value, size = SYMBOL.unpack_from(
                blob, symbol_offset
            )
            if (info & 0x0F) != STT_FUNC:
                continue
            if c_string(strings, name_offset) == TARGET_SYMBOL:
                matches.append((value, size))
    if len(matches) != 1:
        raise SystemExit(f"expected one {TARGET_SYMBOL}, found {matches}")

    function_va, function_size = matches[0]
    function_offset = virtual_to_file(programs, function_va)
    prefix = bytes(blob[
        function_offset:function_offset + len(EXPECTED_FUNCTION_PREFIX)
    ])
    if prefix != EXPECTED_FUNCTION_PREFIX:
        raise SystemExit(
            "GetCulture function signature mismatch: " + prefix.hex()
        )

    branch_va = (
        function_va + len(EXPECTED_FUNCTION_PREFIX) - len(ORIGINAL_BRANCH)
    )
    branch_offset = virtual_to_file(programs, branch_va)
    if bytes(blob[branch_offset:branch_offset + 2]) != ORIGINAL_BRANCH:
        raise SystemExit("GetCulture fallback branch is not the expected JE +0x26")

    # The fallback literal is referenced by LEA at function + 0x43. Resolve it
    # from the exact instruction rather than relying on a fixed rodata address.
    lea_offset = function_offset + 0x43
    if bytes(blob[lea_offset:lea_offset + 3]) != bytes.fromhex("488d35"):
        raise SystemExit("GetCulture fallback LEA signature mismatch")
    displacement = struct.unpack_from("<i", blob, lea_offset + 3)[0]
    fallback_va = function_va + 0x4A + displacement
    fallback_offset = virtual_to_file(programs, fallback_va)
    if bytes(blob[
        fallback_offset:fallback_offset + len(FALLBACK_UTF16)
    ]) != FALLBACK_UTF16:
        raise SystemExit("GetCulture fallback literal is not UTF-16LE en-US")

    blob[branch_offset:branch_offset + 2] = PATCHED_BRANCH
    args.elf.write_bytes(blob)
    after = bytes(blob)

    manifest = {
        "schema": 1,
        "patch": "framework-getculture-built-in-en-us-fallback",
        "elf": str(args.elf),
        "symbol": TARGET_SYMBOL,
        "symbol_virtual_address": function_va,
        "symbol_size": function_size,
        "symbol_file_offset": function_offset,
        "branch_virtual_address": branch_va,
        "branch_file_offset": branch_offset,
        "fallback_virtual_address": fallback_va,
        "fallback_file_offset": fallback_offset,
        "fallback": "en-US",
        "original_bytes_hex": ORIGINAL_BRANCH.hex(),
        "patched_bytes_hex": PATCHED_BRANCH.hex(),
        "sha256_before": before_sha,
        "sha256_after": sha256(after),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
