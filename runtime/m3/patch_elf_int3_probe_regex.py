#!/usr/bin/env python3
"""Patch one uniquely ranked ELF64 function selected by a symbol regex."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import struct
from dataclasses import dataclass

ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")
SYMBOL = struct.Struct("<IBBHQQ")
PT_LOAD = 1
SHT_SYMTAB = 2
SHT_DYNSYM = 11
STT_FUNC = 2


@dataclass(frozen=True)
class Section:
    name_offset: int
    section_type: int
    flags: int
    address: int
    offset: int
    size: int
    link: int
    info: int
    alignment: int
    entry_size: int


@dataclass(frozen=True)
class Program:
    program_type: int
    flags: int
    offset: int
    virtual_address: int
    physical_address: int
    file_size: int
    memory_size: int
    alignment: int


def c_string(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", errors="replace")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=pathlib.Path)
    parser.add_argument("--symbol-regex", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--signature-length", type=int, default=16)
    args = parser.parse_args()
    pattern = re.compile(args.symbol_regex)

    blob = bytearray(args.elf.read_bytes())
    before = bytes(blob)
    header = ELF_HEADER.unpack_from(blob, 0)
    ident = header[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit("only little-endian ELF64 is supported")
    (
        _ident, _elf_type, machine, _version, _entry,
        phoff, shoff, _flags, _ehsize, phentsize, phnum,
        shentsize, shnum, shstrndx,
    ) = header
    if machine != 62 or phentsize != PROGRAM_HEADER.size or \
            shentsize != SECTION_HEADER.size:
        raise SystemExit("unexpected ELF64 x86-64 header")

    programs = [Program(*PROGRAM_HEADER.unpack_from(
        blob, phoff + index * phentsize)) for index in range(phnum)]
    sections = [Section(*SECTION_HEADER.unpack_from(
        blob, shoff + index * shentsize)) for index in range(shnum)]
    if shstrndx >= len(sections):
        raise SystemExit("invalid section-name table")
    shstr = sections[shstrndx]
    section_names = bytes(blob[shstr.offset:shstr.offset + shstr.size])

    candidates: list[dict[str, object]] = []
    for table_index, section in enumerate(sections):
        if section.section_type not in (SHT_SYMTAB, SHT_DYNSYM):
            continue
        if section.entry_size != SYMBOL.size or section.link >= len(sections):
            continue
        strings_section = sections[section.link]
        strings = bytes(blob[
            strings_section.offset:strings_section.offset + strings_section.size
        ])
        for symbol_index in range(section.size // section.entry_size):
            offset = section.offset + symbol_index * section.entry_size
            name_offset, info, other, shndx, value, size = SYMBOL.unpack_from(
                blob, offset)
            name = c_string(strings, name_offset)
            if not pattern.search(name) or value == 0 or \
                    (info & 0x0F) != STT_FUNC:
                continue
            candidates.append({
                "name": name,
                "value": value,
                "size": size,
                "binding": info >> 4,
                "visibility": other & 0x03,
                "section_index": shndx,
                "symbol_table": c_string(section_names, section.name_offset),
                "symbol_index": symbol_index,
                "table_index": table_index,
            })
    if not candidates:
        raise SystemExit(f"no function matches regex: {args.symbol_regex}")

    def rank(item: dict[str, object]) -> tuple[int, int, int, int, str]:
        name = str(item["name"])
        return (
            0 if item["symbol_table"] == ".dynsym" else 1,
            0 if "IntegrationPlugin" in name else 1,
            -int(item["binding"]),
            -int(item["size"]),
            name,
        )

    candidates.sort(key=rank)
    selected = candidates[0]
    best_rank = rank(selected)[:-1]
    tied = [item for item in candidates if rank(item)[:-1] == best_rank]
    unique_locations = {(int(item["value"]), int(item["size"]))
                        for item in tied}
    if len(unique_locations) != 1:
        raise SystemExit(
            "ambiguous top-ranked regex symbols: " + json.dumps(tied, indent=2))

    value = int(selected["value"])
    file_offset = None
    segment = None
    for program in programs:
        if program.program_type == PT_LOAD and \
                program.virtual_address <= value < \
                program.virtual_address + program.file_size:
            file_offset = program.offset + value - program.virtual_address
            segment = {
                "offset": program.offset,
                "virtual_address": program.virtual_address,
                "file_size": program.file_size,
                "memory_size": program.memory_size,
                "flags": program.flags,
            }
            break
    if file_offset is None or segment is None:
        raise SystemExit("selected function is not file-backed by PT_LOAD")

    length = args.signature_length
    if length < 4 or length > 64 or file_offset + length > len(blob):
        raise SystemExit("invalid probe signature length")
    original = bytes(blob[file_offset:file_offset + length])
    if original[0] == 0xCC:
        raise SystemExit("selected function already begins with INT3")
    blob[file_offset] = 0xCC
    args.elf.write_bytes(blob)

    manifest = {
        "schema": 1,
        "elf": str(args.elf),
        "label": args.label,
        "symbol_regex": args.symbol_regex,
        "candidate_count": len(candidates),
        "candidates": candidates[:32],
        "symbol": selected,
        "virtual_address": value,
        "file_offset": file_offset,
        "segment": segment,
        "signature_length": length,
        "original_bytes_hex": original.hex(),
        "patched_bytes_hex": bytes(blob[file_offset:file_offset + length]).hex(),
        "sha256_before": digest(before),
        "sha256_after": digest(bytes(blob)),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
