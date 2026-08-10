#!/usr/bin/env python3
"""Patch the first byte of a named ELF64 function with INT3.

The script parses ELF headers and symbol tables directly, maps the selected
symbol virtual address through PT_LOAD to a file offset, records an exact
byte signature, and writes a machine-readable manifest.  It is intended for
one-shot guest probes whose signal handler restores the original byte before
resuming the function.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=pathlib.Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--signature-length", type=int, default=16)
    args = parser.parse_args()

    blob = bytearray(args.elf.read_bytes())
    before = bytes(blob)
    if len(blob) < ELF_HEADER.size:
        raise SystemExit("ELF file is too short")

    unpacked = ELF_HEADER.unpack_from(blob, 0)
    ident = unpacked[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit("only little-endian ELF64 is supported")

    (
        _ident, _type, machine, _version, _entry,
        program_offset, section_offset, _flags,
        _header_size, program_entry_size, program_count,
        section_entry_size, section_count, section_name_index,
    ) = unpacked
    if machine != 62:
        raise SystemExit(f"expected x86-64 ELF machine 62, got {machine}")
    if program_entry_size != PROGRAM_HEADER.size:
        raise SystemExit("unexpected ELF64 program-header size")
    if section_entry_size != SECTION_HEADER.size:
        raise SystemExit("unexpected ELF64 section-header size")

    programs: list[Program] = []
    for index in range(program_count):
        start = program_offset + index * program_entry_size
        if start + PROGRAM_HEADER.size > len(blob):
            raise SystemExit("program-header table exceeds file")
        programs.append(Program(*PROGRAM_HEADER.unpack_from(blob, start)))

    sections: list[Section] = []
    for index in range(section_count):
        start = section_offset + index * section_entry_size
        if start + SECTION_HEADER.size > len(blob):
            raise SystemExit("section-header table exceeds file")
        sections.append(Section(*SECTION_HEADER.unpack_from(blob, start)))
    if section_name_index >= len(sections):
        raise SystemExit("invalid section-name string table index")

    section_names_section = sections[section_name_index]
    section_names = bytes(blob[
        section_names_section.offset:
        section_names_section.offset + section_names_section.size
    ])

    matches: list[dict[str, object]] = []
    for section_index, section in enumerate(sections):
        if section.section_type not in (SHT_SYMTAB, SHT_DYNSYM):
            continue
        if section.entry_size != SYMBOL.size or section.link >= len(sections):
            continue
        string_section = sections[section.link]
        strings = bytes(blob[
            string_section.offset:string_section.offset + string_section.size
        ])
        count = section.size // section.entry_size
        for symbol_index in range(count):
            start = section.offset + symbol_index * section.entry_size
            if start + SYMBOL.size > len(blob):
                raise SystemExit("symbol table exceeds file")
            name_offset, info, other, shndx, value, size = SYMBOL.unpack_from(
                blob, start)
            name = c_string(strings, name_offset)
            if name != args.symbol or value == 0 or (info & 0x0F) != STT_FUNC:
                continue
            matches.append({
                "name": name,
                "value": value,
                "size": size,
                "binding": info >> 4,
                "visibility": other & 0x03,
                "section_index": shndx,
                "symbol_table": c_string(section_names, section.name_offset),
                "symbol_index": symbol_index,
                "section_index_of_table": section_index,
            })

    if not matches:
        raise SystemExit(f"function symbol not found: {args.symbol}")
    matches.sort(key=lambda item: (
        item["symbol_table"] != ".dynsym",
        -int(item["binding"]),
        -int(item["size"]),
    ))
    selected = matches[0]
    if len(matches) > 1:
        first_key = (selected["value"], selected["size"])
        for candidate in matches[1:]:
            if (candidate["value"], candidate["size"]) != first_key:
                raise SystemExit(
                    f"ambiguous function symbol {args.symbol}: {matches}")

    value = int(selected["value"])
    file_offset: int | None = None
    segment_record: dict[str, int] | None = None
    for program in programs:
        if program.program_type != PT_LOAD:
            continue
        if (program.virtual_address <= value <
                program.virtual_address + program.file_size):
            file_offset = program.offset + (value - program.virtual_address)
            segment_record = {
                "offset": program.offset,
                "virtual_address": program.virtual_address,
                "file_size": program.file_size,
                "memory_size": program.memory_size,
                "flags": program.flags,
            }
            break
    if file_offset is None or segment_record is None:
        raise SystemExit("symbol does not map into a file-backed PT_LOAD")

    signature_length = args.signature_length
    if signature_length < 4 or signature_length > 64:
        raise SystemExit("signature length must be between 4 and 64")
    if file_offset + signature_length > len(blob):
        raise SystemExit("probe signature exceeds ELF file")
    original = bytes(blob[file_offset:file_offset + signature_length])
    if original[0] == 0xCC:
        raise SystemExit("selected function already starts with INT3")

    blob[file_offset] = 0xCC
    args.elf.write_bytes(blob)
    manifest = {
        "schema": 1,
        "elf": str(args.elf),
        "label": args.label,
        "symbol": selected,
        "virtual_address": value,
        "file_offset": file_offset,
        "segment": segment_record,
        "signature_length": signature_length,
        "original_bytes_hex": original.hex(),
        "patched_bytes_hex": bytes(blob[
            file_offset:file_offset + signature_length]).hex(),
        "sha256_before": sha256(before),
        "sha256_after": sha256(bytes(blob)),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
