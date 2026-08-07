#!/usr/bin/env python3
"""Patch a verified function in a stripped Qt ELF using RTTI/vtable evidence.

The target can be selected either by an exact exported ELF symbol or by a
simple-class RTTI name plus a virtual-table slot.  Optional resolution steps
follow local tail jumps and select a local constructor-like call after the
operator-new PLT call.  Every step is fail-closed and recorded in a JSON
manifest before a one-shot INT3 byte is installed.
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
RELA = struct.Struct("<QQq")

PT_LOAD = 1
PF_X = 1
SHT_SYMTAB = 2
SHT_DYNSYM = 11
SHT_RELA = 4
STT_FUNC = 2
R_X86_64_64 = 1
R_X86_64_RELATIVE = 8


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
class SymbolRecord:
    name: str
    value: int
    size: int
    info: int
    other: int
    section_index: int
    table: str
    index: int

    @property
    def symbol_type(self) -> int:
        return self.info & 0x0F

    @property
    def binding(self) -> int:
        return self.info >> 4


@dataclass(frozen=True)
class Relocation:
    offset: int
    relocation_type: int
    symbol_index: int
    symbol_name: str
    symbol_info: int
    symbol_section_index: int
    addend: int
    section: str
    index: int


class Elf64:
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.blob = bytearray(path.read_bytes())
        self.before = bytes(self.blob)
        if len(self.blob) < ELF_HEADER.size:
            raise SystemExit("ELF file is truncated")
        header = ELF_HEADER.unpack_from(self.blob, 0)
        ident = header[0]
        if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
            raise SystemExit("only little-endian ELF64 is supported")
        (
            _ident,
            _elf_type,
            machine,
            _version,
            _entry,
            self.program_header_offset,
            self.section_header_offset,
            _flags,
            _header_size,
            program_entry_size,
            program_count,
            section_entry_size,
            section_count,
            section_name_index,
        ) = header
        if machine != 62:
            raise SystemExit("only ELF64 x86-64 is supported")
        if program_entry_size != PROGRAM_HEADER.size:
            raise SystemExit("unexpected ELF program-header size")
        if section_entry_size != SECTION_HEADER.size:
            raise SystemExit("unexpected ELF section-header size")

        self.programs = [
            Program(*PROGRAM_HEADER.unpack_from(
                self.blob,
                self.program_header_offset + index * program_entry_size,
            ))
            for index in range(program_count)
        ]
        self.sections = [
            Section(*SECTION_HEADER.unpack_from(
                self.blob,
                self.section_header_offset + index * section_entry_size,
            ))
            for index in range(section_count)
        ]
        if section_name_index >= len(self.sections):
            raise SystemExit("invalid section-name string table")
        section_names = self.sections[section_name_index]
        section_name_data = bytes(self.blob[
            section_names.offset:section_names.offset + section_names.size
        ])
        self.section_names = [
            self.c_string(section_name_data, section.name_offset)
            for section in self.sections
        ]
        self.section_by_name = {
            name: section
            for name, section in zip(self.section_names, self.sections)
            if name
        }

        self.symbol_tables: dict[str, list[SymbolRecord]] = {}
        for table_index, section in enumerate(self.sections):
            if section.section_type not in (SHT_SYMTAB, SHT_DYNSYM):
                continue
            table_name = self.section_names[table_index]
            if section.entry_size != SYMBOL.size or section.link >= len(self.sections):
                raise SystemExit(f"invalid symbol table {table_name}")
            strings_section = self.sections[section.link]
            strings = bytes(self.blob[
                strings_section.offset:strings_section.offset + strings_section.size
            ])
            records: list[SymbolRecord] = []
            for symbol_index in range(section.size // section.entry_size):
                offset = section.offset + symbol_index * section.entry_size
                name_offset, info, other, shndx, value, size = SYMBOL.unpack_from(
                    self.blob, offset)
                records.append(SymbolRecord(
                    name=self.c_string(strings, name_offset),
                    value=value,
                    size=size,
                    info=info,
                    other=other,
                    section_index=shndx,
                    table=table_name,
                    index=symbol_index,
                ))
            self.symbol_tables[table_name] = records

        dynsym = self.symbol_tables.get(".dynsym")
        if dynsym is None:
            raise SystemExit("ELF has no .dynsym")
        self.relocations: dict[int, Relocation] = {}
        self.relocation_lists: dict[str, list[Relocation]] = {}
        for section_index, section in enumerate(self.sections):
            if section.section_type != SHT_RELA:
                continue
            name = self.section_names[section_index]
            if section.entry_size != RELA.size:
                raise SystemExit(f"unexpected relocation entry size in {name}")
            entries: list[Relocation] = []
            for index in range(section.size // section.entry_size):
                offset, info, addend = RELA.unpack_from(
                    self.blob, section.offset + index * section.entry_size)
                relocation_type = info & 0xFFFFFFFF
                symbol_index = info >> 32
                if symbol_index >= len(dynsym):
                    raise SystemExit(f"invalid dynamic symbol index in {name}")
                symbol = dynsym[symbol_index]
                record = Relocation(
                    offset=offset,
                    relocation_type=relocation_type,
                    symbol_index=symbol_index,
                    symbol_name=symbol.name,
                    symbol_info=symbol.info,
                    symbol_section_index=symbol.section_index,
                    addend=addend,
                    section=name,
                    index=index,
                )
                entries.append(record)
                if offset in self.relocations:
                    raise SystemExit(f"duplicate relocation at 0x{offset:x}")
                self.relocations[offset] = record
            self.relocation_lists[name] = entries

    @staticmethod
    def c_string(data: bytes, offset: int) -> str:
        if offset < 0 or offset >= len(data):
            return ""
        end = data.find(b"\0", offset)
        if end < 0:
            end = len(data)
        return data[offset:end].decode("utf-8", errors="replace")

    def virtual_to_file(self, address: int) -> int:
        for program in self.programs:
            if program.program_type != PT_LOAD:
                continue
            if program.virtual_address <= address < \
                    program.virtual_address + program.file_size:
                return program.offset + address - program.virtual_address
        raise SystemExit(f"virtual address 0x{address:x} is not file-backed")

    def file_to_virtual(self, offset: int) -> int:
        for program in self.programs:
            if program.program_type != PT_LOAD:
                continue
            if program.offset <= offset < program.offset + program.file_size:
                return program.virtual_address + offset - program.offset
        raise SystemExit(f"file offset 0x{offset:x} is not loadable")

    def is_executable(self, address: int) -> bool:
        return any(
            program.program_type == PT_LOAD and (program.flags & PF_X) and
            program.virtual_address <= address <
            program.virtual_address + program.file_size
            for program in self.programs
        )

    def section_contains(self, name: str, address: int) -> bool:
        section = self.section_by_name.get(name)
        return bool(section and section.address <= address < section.address + section.size)

    def read_u64(self, address: int) -> int:
        return struct.unpack_from("<Q", self.blob, self.virtual_to_file(address))[0]

    def read_i64(self, address: int) -> int:
        return struct.unpack_from("<q", self.blob, self.virtual_to_file(address))[0]

    def read_bytes(self, address: int, length: int) -> bytes:
        offset = self.virtual_to_file(address)
        if offset + length > len(self.blob):
            raise SystemExit("requested bytes exceed ELF file")
        return bytes(self.blob[offset:offset + length])

    def exact_symbol(self, name: str) -> SymbolRecord:
        candidates: list[SymbolRecord] = []
        for records in self.symbol_tables.values():
            candidates.extend(
                symbol for symbol in records
                if symbol.name == name and symbol.value != 0 and
                symbol.symbol_type == STT_FUNC
            )
        if not candidates:
            raise SystemExit(f"defined function symbol was not found: {name}")
        locations = {(item.value, item.size) for item in candidates}
        if len(locations) != 1:
            raise SystemExit(
                "symbol resolves to multiple locations: " +
                json.dumps([symbol_to_json(item) for item in candidates], indent=2))
        candidates.sort(key=lambda item: (
            0 if item.table == ".dynsym" else 1,
            -item.binding,
            -item.size,
        ))
        return candidates[0]

    def find_exact_alloc_string(self, text: str) -> int:
        needle = text.encode("utf-8") + b"\0"
        matches: list[int] = []
        for section in self.sections:
            if not (section.flags & 0x2) or section.size == 0:  # SHF_ALLOC
                continue
            data = bytes(self.blob[section.offset:section.offset + section.size])
            start = 0
            while True:
                found = data.find(needle, start)
                if found < 0:
                    break
                matches.append(section.address + found)
                start = found + 1
        if len(matches) != 1:
            raise SystemExit(
                f"expected one allocated string {text!r}, found " +
                json.dumps([f"0x{value:x}" for value in matches]))
        return matches[0]

    def relative_references(self, target: int) -> list[Relocation]:
        return [
            relocation for relocation in self.relocations.values()
            if relocation.relocation_type == R_X86_64_RELATIVE and
            relocation.addend == target
        ]

    def relocation_target(self, relocation: Relocation) -> int | None:
        if relocation.relocation_type == R_X86_64_RELATIVE:
            return relocation.addend
        if relocation.relocation_type == R_X86_64_64 and \
                relocation.symbol_section_index != 0:
            symbols = self.symbol_tables[".dynsym"]
            return symbols[relocation.symbol_index].value + relocation.addend
        return None

    def plt_address(self, symbol_name: str) -> int:
        relocs = self.relocation_lists.get(".rela.plt")
        plt = self.section_by_name.get(".plt")
        if relocs is None or plt is None:
            raise SystemExit("ELF lacks .rela.plt or .plt")
        matches = [item for item in relocs if item.symbol_name == symbol_name]
        if len(matches) != 1:
            raise SystemExit(
                f"expected one PLT relocation for {symbol_name}, found {len(matches)}")
        entry_size = plt.entry_size or 16
        return plt.address + (matches[0].index + 1) * entry_size


def symbol_to_json(symbol: SymbolRecord) -> dict[str, object]:
    return {
        "name": symbol.name,
        "value": symbol.value,
        "size": symbol.size,
        "binding": symbol.binding,
        "type": symbol.symbol_type,
        "section_index": symbol.section_index,
        "symbol_table": symbol.table,
        "symbol_index": symbol.index,
    }


def relocation_to_json(relocation: Relocation) -> dict[str, object]:
    return {
        "offset": relocation.offset,
        "type": relocation.relocation_type,
        "symbol_index": relocation.symbol_index,
        "symbol_name": relocation.symbol_name,
        "symbol_section_index": relocation.symbol_section_index,
        "addend": relocation.addend,
        "relocation_section": relocation.section,
        "relocation_index": relocation.index,
    }


def resolve_vtable_target(
    elf: Elf64,
    class_name: str,
    slot: int,
) -> tuple[int, dict[str, object]]:
    if not class_name or class_name[0].isdigit() or "::" in class_name:
        raise SystemExit(
            "--class-name must be a simple unqualified C++ class name")
    if slot < 0 or slot > 512:
        raise SystemExit("invalid vtable slot")
    encoded_name = f"{len(class_name)}{class_name}"
    name_address = elf.find_exact_alloc_string(encoded_name)
    name_references = elf.relative_references(name_address)
    if len(name_references) != 1:
        raise SystemExit(
            f"expected one RTTI name reference for {class_name}, found "
            f"{len(name_references)}")
    name_reference = name_references[0]
    typeinfo_address = name_reference.offset - 8
    typeinfo_vptr = elf.relocations.get(typeinfo_address)
    if typeinfo_vptr is None or \
            "class_type_info" not in typeinfo_vptr.symbol_name:
        raise SystemExit(
            f"RTTI object at 0x{typeinfo_address:x} has no class-type-info vptr")
    if elf.relocations.get(typeinfo_address + 8) != name_reference:
        raise SystemExit("RTTI name relocation is not at typeinfo+8")

    candidate_records: list[dict[str, object]] = []
    valid_candidates: list[dict[str, object]] = []
    for reference in elf.relative_references(typeinfo_address):
        record: dict[str, object] = {
            "typeinfo_reference": relocation_to_json(reference),
        }
        try:
            offset_to_top = elf.read_i64(reference.offset - 8)
        except SystemExit as error:
            record["rejection"] = str(error)
            candidate_records.append(record)
            continue
        address_point = reference.offset + 8
        first_entry = elf.relocations.get(address_point)
        first_target = (
            elf.relocation_target(first_entry) if first_entry is not None else None
        )
        record.update({
            "vtable_start": reference.offset - 8,
            "offset_to_top": offset_to_top,
            "address_point": address_point,
            "first_entry": (
                relocation_to_json(first_entry) if first_entry else None),
            "first_target": first_target,
        })
        if offset_to_top != 0:
            record["rejection"] = "not a primary vtable"
        elif first_entry is None or first_target is None or \
                not elf.is_executable(first_target):
            record["rejection"] = "first virtual entry is not executable"
        else:
            valid_candidates.append(record)
        candidate_records.append(record)
    if len(valid_candidates) != 1:
        raise SystemExit(
            f"expected one primary vtable for {class_name}, found "
            f"{len(valid_candidates)}: " + json.dumps(candidate_records, indent=2))
    vtable = valid_candidates[0]
    address_point = int(vtable["address_point"])
    entry_address = address_point + slot * 8
    entry = elf.relocations.get(entry_address)
    if entry is None:
        raise SystemExit(
            f"vtable slot {slot} at 0x{entry_address:x} has no relocation")
    target = elf.relocation_target(entry)
    if target is None or not elf.is_executable(target):
        raise SystemExit(
            f"vtable slot {slot} does not resolve to a local executable target: "
            + json.dumps(relocation_to_json(entry), indent=2))
    resolution = {
        "mode": "qt-rtti-vtable",
        "class_name": class_name,
        "itanium_type_name": encoded_name,
        "type_name_address": name_address,
        "type_name_reference": relocation_to_json(name_reference),
        "typeinfo_address": typeinfo_address,
        "typeinfo_vptr": relocation_to_json(typeinfo_vptr),
        "vtable_candidates": candidate_records,
        "selected_vtable_start": int(vtable["vtable_start"]),
        "selected_vtable_address_point": address_point,
        "vtable_slot": slot,
        "vtable_entry_address": entry_address,
        "vtable_entry": relocation_to_json(entry),
        "virtual_function_address": target,
    }
    return target, resolution


def direct_rel32_candidates(
    elf: Elf64,
    start: int,
    opcode: int,
    scan_bytes: int,
) -> list[dict[str, int]]:
    if scan_bytes < 5 or scan_bytes > 4096:
        raise SystemExit("invalid direct-branch scan length")
    data = elf.read_bytes(start, scan_bytes)
    candidates: list[dict[str, int]] = []
    occupied: list[range] = []
    for index in range(0, len(data) - 4):
        address = start + index
        if any(address in interval for interval in occupied):
            continue
        if data[index] != opcode:
            continue
        relative = struct.unpack_from("<i", data, index + 1)[0]
        target = address + 5 + relative
        if not elf.is_executable(target):
            continue
        candidates.append({
            "instruction_address": address,
            "target": target,
            "relative": relative,
        })
        occupied.append(range(address + 1, address + 5))
    return candidates


def follow_tail_jumps(
    elf: Elf64,
    target: int,
    count: int,
    scan_bytes: int,
) -> tuple[int, list[dict[str, object]]]:
    steps: list[dict[str, object]] = []
    current = target
    for index in range(count):
        candidates = [
            candidate for candidate in direct_rel32_candidates(
                elf, current, 0xE9, scan_bytes)
            if elf.section_contains(".text", candidate["target"])
        ]
        if len(candidates) != 1:
            raise SystemExit(
                f"tail-jump step {index} from 0x{current:x} found "
                f"{len(candidates)} local E9 targets: " +
                json.dumps(candidates, indent=2))
        selected = candidates[0]
        steps.append({
            "step": index,
            "source_function": current,
            "candidates": candidates,
            "selected": selected,
        })
        current = selected["target"]
    return current, steps


def select_local_call_after_new(
    elf: Elf64,
    target: int,
    index: int,
    scan_bytes: int,
) -> tuple[int, dict[str, object]]:
    if index < 0:
        raise SystemExit("local-call index must be non-negative")
    new_plt = elf.plt_address("_Znwm")
    calls = direct_rel32_candidates(elf, target, 0xE8, scan_bytes)
    new_calls = [item for item in calls if item["target"] == new_plt]
    if len(new_calls) != 1:
        raise SystemExit(
            f"expected one operator-new call from 0x{target:x}, found "
            f"{len(new_calls)}: " + json.dumps(calls, indent=2))
    new_call = new_calls[0]
    local_calls = [
        item for item in calls
        if item["instruction_address"] >= new_call["instruction_address"] + 5 and
        elf.section_contains(".text", item["target"])
    ]
    if index >= len(local_calls):
        raise SystemExit(
            f"local call index {index} is out of range after operator new: " +
            json.dumps(local_calls, indent=2))
    selected = local_calls[index]
    return selected["target"], {
        "source_function": target,
        "operator_new_symbol": "_Znwm",
        "operator_new_plt": new_plt,
        "all_direct_calls": calls,
        "operator_new_call": new_call,
        "local_calls_after_new": local_calls,
        "selected_local_call_index": index,
        "selected_local_call": selected,
    }


def parse_expected_address(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        result = int(value, 0)
    except ValueError as error:
        raise SystemExit(f"invalid expected address: {value}") from error
    if result <= 0:
        raise SystemExit("expected address must be positive")
    return result


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=pathlib.Path)
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--symbol")
    target_group.add_argument("--class-name")
    parser.add_argument("--vtable-slot", type=int)
    parser.add_argument("--follow-tail-jumps", type=int, default=0)
    parser.add_argument("--local-call-after-new-index", type=int)
    parser.add_argument("--scan-bytes", type=int, default=128)
    parser.add_argument("--expected-address")
    parser.add_argument("--label", required=True)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--signature-length", type=int, default=16)
    args = parser.parse_args()

    if args.symbol is not None and args.vtable_slot is not None:
        raise SystemExit("--vtable-slot is only valid with --class-name")
    if args.class_name is not None and args.vtable_slot is None:
        raise SystemExit("--class-name requires --vtable-slot")
    if args.follow_tail_jumps < 0 or args.follow_tail_jumps > 8:
        raise SystemExit("invalid --follow-tail-jumps value")

    elf = Elf64(args.elf)
    if args.symbol is not None:
        symbol = elf.exact_symbol(args.symbol)
        target = symbol.value
        resolution: dict[str, object] = {
            "mode": "exact-symbol",
            "symbol": symbol_to_json(symbol),
            "virtual_function_address": target,
        }
    else:
        target, resolution = resolve_vtable_target(
            elf, args.class_name, args.vtable_slot)

    virtual_function_address = target
    target, tail_steps = follow_tail_jumps(
        elf, target, args.follow_tail_jumps, args.scan_bytes)
    if tail_steps:
        resolution["tail_jump_steps"] = tail_steps
        resolution["after_tail_jumps"] = target

    if args.local_call_after_new_index is not None:
        target, call_resolution = select_local_call_after_new(
            elf,
            target,
            args.local_call_after_new_index,
            args.scan_bytes,
        )
        resolution["local_call_after_operator_new"] = call_resolution

    expected = parse_expected_address(args.expected_address)
    if expected is not None and target != expected:
        raise SystemExit(
            f"resolved target 0x{target:x} does not match expected 0x{expected:x}")
    if not elf.is_executable(target):
        raise SystemExit(f"resolved target 0x{target:x} is not executable")

    length = args.signature_length
    if length < 4 or length > 64:
        raise SystemExit("invalid probe signature length")
    file_offset = elf.virtual_to_file(target)
    if file_offset + length > len(elf.blob):
        raise SystemExit("probe signature exceeds ELF file")
    original = bytes(elf.blob[file_offset:file_offset + length])
    if original[0] == 0xCC:
        raise SystemExit("resolved target already begins with INT3")
    elf.blob[file_offset] = 0xCC
    after = bytes(elf.blob)
    args.elf.write_bytes(after)

    compatibility_symbol = (
        symbol_to_json(symbol) if args.symbol is not None else {
            "name": f"<resolved:{args.label}>",
            "value": target,
            "size": 0,
            "binding": 0,
            "type": STT_FUNC,
            "section_index": None,
            "symbol_table": "RTTI/vtable resolution",
            "symbol_index": None,
        }
    )
    manifest = {
        "schema": 2,
        "elf": str(args.elf),
        "label": args.label,
        # Compatibility fields consumed by augment_int3_probe.py and the
        # existing proof summarizer.  The detailed fail-closed evidence is in
        # the resolution object below.
        "symbol": compatibility_symbol,
        "virtual_address": target,
        "resolution": resolution,
        "virtual_function_address": virtual_function_address,
        "patch_target_address": target,
        "expected_address": expected,
        "file_offset": file_offset,
        "signature_length": length,
        "original_bytes_hex": original.hex(),
        "patched_bytes_hex": bytes(
            elf.blob[file_offset:file_offset + length]).hex(),
        "sha256_before": digest(elf.before),
        "sha256_after": digest(after),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
