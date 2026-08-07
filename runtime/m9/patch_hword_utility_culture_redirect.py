#!/usr/bin/env python3
"""Redirect CHwordUtilityEx culture lookup to its working locale provider.

The exact HOffice 11.20.0.1520 HWord startup constructs two locale strings
through adjacent virtual methods on ``CHwordUtilityEx``:

* vtable byte offset ``0x130`` calls ``Hnc::Framework::GetCulture()`` and is
  empty in the clean-room macOS runtime;
* vtable byte offset ``0x138`` calls ``GetSystemDefaultLCID`` plus
  ``HncGetLocaleInfo`` and returns the required ``en-US`` string.

HWord immediately executes ``substr(3)`` on both results.  This patch changes
only the ``R_X86_64_RELATIVE`` addend that populates vtable slot ``0x130`` so
that it points at the already-working slot ``0x138`` implementation.  No code
bytes, ELF layout, symbol, or unrelated virtual method is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import struct

ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")
RELA = struct.Struct("<QQq")

PT_LOAD = 1
SHT_RELA = 4
R_X86_64_RELATIVE = 8

TYPE_NAME = b"15CHwordUtilityEx\0"
TYPE_NAME_VA = 0x0166A3D0
TYPEINFO_VA = 0x01A27D48
TYPEINFO_NAME_POINTER_VA = TYPEINFO_VA + 8
VTABLE_ADDRESS_POINT = 0x019F5A50
VTABLE_TYPEINFO_POINTER_VA = VTABLE_ADDRESS_POINT - 8
SOURCE_SLOT_BYTE_OFFSET = 0x130
TARGET_SLOT_BYTE_OFFSET = 0x138
SOURCE_SLOT_VA = VTABLE_ADDRESS_POINT + SOURCE_SLOT_BYTE_OFFSET
TARGET_SLOT_VA = VTABLE_ADDRESS_POINT + TARGET_SLOT_BYTE_OFFSET
SOURCE_METHOD_VA = 0x00411100
TARGET_METHOD_VA = 0x00412380

# Exact entry signatures provide a second independent lock beyond relocation
# metadata.  The source calls GetFramework and dispatches Framework slot 0x128;
# the target allocates its locale buffer and calls GetSystemDefaultLCID.
SOURCE_METHOD_PREFIX = bytes.fromhex(
    "41544989fc554889f5534883ec10e86d40d9ff488d5c2408488b104889c64889df"
)
TARGET_METHOD_PREFIX = bytes.fromhex(
    "415431c0b9000400004989f4554889fd534881ec002000004889e74889e3f348ab"
)


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


@dataclass(frozen=True)
class Relocation:
    index: int
    file_offset: int
    target: int
    info: int
    addend: int

    @property
    def relocation_type(self) -> int:
        return self.info & 0xFFFFFFFF

    @property
    def symbol_index(self) -> int:
        return self.info >> 32


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def c_string(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", errors="replace")


def virtual_to_file(programs: list[Program], address: int) -> int:
    matches = [
        program.offset + address - program.virtual_address
        for program in programs
        if program.program_type == PT_LOAD
        and program.virtual_address <= address
        < program.virtual_address + program.file_size
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"virtual address 0x{address:x} has {len(matches)} file mappings"
        )
    return matches[0]


def require_relative(relocation: Relocation, *, target: int,
                     addend: int, label: str) -> None:
    if relocation.target != target:
        raise SystemExit(
            f"{label}: target 0x{relocation.target:x} != 0x{target:x}"
        )
    if relocation.relocation_type != R_X86_64_RELATIVE or \
            relocation.symbol_index != 0:
        raise SystemExit(
            f"{label}: expected R_X86_64_RELATIVE/symbol 0, got "
            f"type {relocation.relocation_type}, symbol "
            f"{relocation.symbol_index}"
        )
    if relocation.addend != addend:
        raise SystemExit(
            f"{label}: addend 0x{relocation.addend:x} != 0x{addend:x}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-output-sha256", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    blob = bytearray(args.elf.read_bytes())
    before = bytes(blob)
    before_sha256 = digest(before)
    if before_sha256 != args.expected_sha256:
        raise SystemExit(
            f"unexpected input SHA-256: {before_sha256} != "
            f"{args.expected_sha256}"
        )

    header = ELF_HEADER.unpack_from(blob, 0)
    ident = header[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit("only little-endian ELF64 is supported")
    (
        _ident, _elf_type, machine, _version, _entry,
        program_offset, section_offset, _flags, _header_size,
        program_entry_size, program_count, section_entry_size,
        section_count, section_name_index,
    ) = header
    if machine != 62 or program_entry_size != PROGRAM_HEADER.size or \
            section_entry_size != SECTION_HEADER.size:
        raise SystemExit("unexpected ELF64 x86-64 layout")

    programs = [Program(*PROGRAM_HEADER.unpack_from(
        blob, program_offset + index * program_entry_size
    )) for index in range(program_count)]
    sections = [Section(*SECTION_HEADER.unpack_from(
        blob, section_offset + index * section_entry_size
    )) for index in range(section_count)]
    if section_name_index >= len(sections):
        raise SystemExit("invalid section-name string table index")
    names_section = sections[section_name_index]
    names = bytes(blob[
        names_section.offset:names_section.offset + names_section.size
    ])

    rela_sections = [
        section for section in sections
        if section.section_type == SHT_RELA
        and c_string(names, section.name_offset) == ".rela.dyn"
    ]
    if len(rela_sections) != 1:
        raise SystemExit(
            f"expected one .rela.dyn section, found {len(rela_sections)}"
        )
    rela_section = rela_sections[0]
    if rela_section.entry_size != RELA.size or \
            rela_section.size % RELA.size != 0:
        raise SystemExit("unexpected .rela.dyn entry layout")

    relocations: dict[int, Relocation] = {}
    for index in range(rela_section.size // rela_section.entry_size):
        file_offset = rela_section.offset + index * rela_section.entry_size
        target, info, addend = RELA.unpack_from(blob, file_offset)
        if target in relocations:
            raise SystemExit(
                f"duplicate .rela.dyn target 0x{target:x}"
            )
        relocations[target] = Relocation(
            index=index,
            file_offset=file_offset,
            target=target,
            info=info,
            addend=addend,
        )

    type_name_offset = virtual_to_file(programs, TYPE_NAME_VA)
    actual_type_name = bytes(blob[
        type_name_offset:type_name_offset + len(TYPE_NAME)
    ])
    if actual_type_name != TYPE_NAME:
        raise SystemExit(
            f"CHwordUtilityEx RTTI name mismatch: {actual_type_name!r}"
        )

    type_name_relocation = relocations.get(TYPEINFO_NAME_POINTER_VA)
    if type_name_relocation is None:
        raise SystemExit("missing CHwordUtilityEx type-name relocation")
    require_relative(
        type_name_relocation,
        target=TYPEINFO_NAME_POINTER_VA,
        addend=TYPE_NAME_VA,
        label="CHwordUtilityEx type-name relocation",
    )

    vtable_typeinfo_relocation = relocations.get(VTABLE_TYPEINFO_POINTER_VA)
    if vtable_typeinfo_relocation is None:
        raise SystemExit("missing CHwordUtilityEx vtable RTTI relocation")
    require_relative(
        vtable_typeinfo_relocation,
        target=VTABLE_TYPEINFO_POINTER_VA,
        addend=TYPEINFO_VA,
        label="CHwordUtilityEx vtable RTTI relocation",
    )

    source_relocation = relocations.get(SOURCE_SLOT_VA)
    target_relocation = relocations.get(TARGET_SLOT_VA)
    if source_relocation is None or target_relocation is None:
        raise SystemExit("missing CHwordUtilityEx locale vtable relocation")
    require_relative(
        source_relocation,
        target=SOURCE_SLOT_VA,
        addend=SOURCE_METHOD_VA,
        label="CHwordUtilityEx culture slot",
    )
    require_relative(
        target_relocation,
        target=TARGET_SLOT_VA,
        addend=TARGET_METHOD_VA,
        label="CHwordUtilityEx system-locale slot",
    )
    if target_relocation.index != source_relocation.index + 1 or \
            target_relocation.file_offset != \
            source_relocation.file_offset + RELA.size:
        raise SystemExit("locale vtable relocations are not adjacent")

    source_method_offset = virtual_to_file(programs, SOURCE_METHOD_VA)
    target_method_offset = virtual_to_file(programs, TARGET_METHOD_VA)
    source_prefix = bytes(blob[
        source_method_offset:source_method_offset + len(SOURCE_METHOD_PREFIX)
    ])
    target_prefix = bytes(blob[
        target_method_offset:target_method_offset + len(TARGET_METHOD_PREFIX)
    ])
    if source_prefix != SOURCE_METHOD_PREFIX:
        raise SystemExit(
            "culture provider method signature mismatch: " +
            source_prefix.hex()
        )
    if target_prefix != TARGET_METHOD_PREFIX:
        raise SystemExit(
            "system-locale method signature mismatch: " +
            target_prefix.hex()
        )

    addend_file_offset = source_relocation.file_offset + 16
    original_addend_bytes = bytes(blob[
        addend_file_offset:addend_file_offset + 8
    ])
    expected_addend_bytes = struct.pack("<q", SOURCE_METHOD_VA)
    if original_addend_bytes != expected_addend_bytes:
        raise SystemExit(
            "source relocation addend bytes do not match parsed value"
        )
    patched_addend_bytes = struct.pack("<q", TARGET_METHOD_VA)
    blob[addend_file_offset:addend_file_offset + 8] = patched_addend_bytes

    patched_target, patched_info, patched_addend = RELA.unpack_from(
        blob, source_relocation.file_offset
    )
    if patched_target != SOURCE_SLOT_VA or patched_info != \
            source_relocation.info or patched_addend != TARGET_METHOD_VA:
        raise SystemExit("post-patch relocation verification failed")

    after = bytes(blob)
    after_sha256 = digest(after)
    if after_sha256 != args.expected_output_sha256:
        raise SystemExit(
            f"unexpected output SHA-256: {after_sha256} != "
            f"{args.expected_output_sha256}"
        )
    args.elf.write_bytes(after)

    manifest = {
        "schema": 1,
        "patch": "chwordutilityex-culture-slot-to-system-locale-slot",
        "elf": str(args.elf),
        "type_name": TYPE_NAME[:-1].decode("ascii"),
        "type_name_virtual_address": TYPE_NAME_VA,
        "typeinfo_virtual_address": TYPEINFO_VA,
        "vtable_address_point": VTABLE_ADDRESS_POINT,
        "source_slot_byte_offset": SOURCE_SLOT_BYTE_OFFSET,
        "target_slot_byte_offset": TARGET_SLOT_BYTE_OFFSET,
        "source_slot_virtual_address": SOURCE_SLOT_VA,
        "target_slot_virtual_address": TARGET_SLOT_VA,
        "source_method_virtual_address": SOURCE_METHOD_VA,
        "target_method_virtual_address": TARGET_METHOD_VA,
        "source_relocation_index": source_relocation.index,
        "source_relocation_file_offset": source_relocation.file_offset,
        "target_relocation_index": target_relocation.index,
        "target_relocation_file_offset": target_relocation.file_offset,
        "addend_file_offset": addend_file_offset,
        "original_addend_bytes_hex": original_addend_bytes.hex(),
        "patched_addend_bytes_hex": patched_addend_bytes.hex(),
        "sha256_before": before_sha256,
        "sha256_after": after_sha256,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
