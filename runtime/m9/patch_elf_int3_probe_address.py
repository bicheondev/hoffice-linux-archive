#!/usr/bin/env python3
"""Patch one signature-locked executable ELF address with an INT3 byte.

The requested virtual address remains the primary lock.  When an expected byte
prefix is supplied and that address does not match, the patcher may search a
small symmetric window for exactly one matching instruction boundary.  This
handles documented disassembly transcription drift while remaining
fail-closed: zero or multiple nearby matches abort without modifying the ELF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    parser.add_argument(
        "--nearby-search", type=parse_int, default=16,
        help="unique signature search radius when the requested site differs")
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    if args.signature_length < 4 or args.signature_length > 128:
        raise SystemExit("signature length must be in 4..128")
    if args.nearby_search < 0 or args.nearby_search > 4096:
        raise SystemExit("nearby search must be in 0..4096")
    requested_expected = bytes.fromhex(args.expected_prefix) if args.expected_prefix else b""
    expected = requested_expected

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

    executable_segments: list[dict[str, int]] = []
    for index in range(program_count):
        offset = program_offset + index * program_entry_size
        if offset + PROGRAM_HEADER.size > len(blob):
            raise SystemExit("truncated program-header table")
        values = PROGRAM_HEADER.unpack_from(blob, offset)
        p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz, p_memsz, p_align = values
        if p_type == PT_LOAD and (p_flags & PF_X) != 0:
            executable_segments.append({
                "index": index,
                "flags": p_flags,
                "file_offset": p_offset,
                "virtual_address": p_vaddr,
                "file_size": p_filesz,
                "memory_size": p_memsz,
                "alignment": p_align,
            })

    requested_target = args.virtual_address

    def locate(virtual_address: int) -> tuple[int, dict[str, int]] | None:
        for candidate in executable_segments:
            start = candidate["virtual_address"]
            if start <= virtual_address < start + candidate["file_size"]:
                return candidate["file_offset"] + virtual_address - start, candidate
        return None

    requested = locate(requested_target)
    if requested is None:
        raise SystemExit("target is not inside an executable PT_LOAD file range")
    requested_file_offset, requested_segment = requested

    target = requested_target
    file_offset = requested_file_offset
    segment = requested_segment
    relocation_delta = 0
    correction = None

    if expected:
        requested_bytes = bytes(blob[file_offset:file_offset + len(expected)])
        if requested_bytes != expected:
            # The first conversion workflow transcribed the post-call boundary
            # as 0x411136/4889e8.  Exact disassembly of the locked HwordApp
            # object shows 0x411136 is the three-byte `call *0x20(%rax)` and
            # the first post-call instruction is 0x411139/48837d0800.  Apply
            # only this fully locked correction; all other sites still use the
            # generic unique nearby signature search below.
            if (
                args.label == "culture-conversion-after"
                and os.environ.get("PROBE_MODE") == "after"
                and requested_target == 0x411136
                and requested_expected == bytes.fromhex("4889e8")
                and bytes(blob[file_offset:file_offset + 3]) == bytes.fromhex("ff5020")
            ):
                corrected_target = requested_target + 3
                corrected = locate(corrected_target)
                corrected_expected = bytes.fromhex("48837d0800")
                if corrected is None:
                    raise SystemExit("corrected post-call target is not executable")
                corrected_offset, corrected_segment = corrected
                actual = bytes(blob[corrected_offset:corrected_offset + len(corrected_expected)])
                if actual != corrected_expected:
                    raise SystemExit(
                        "locked post-call correction mismatch: expected "
                        + corrected_expected.hex() + ", found " + actual.hex())
                target = corrected_target
                file_offset = corrected_offset
                segment = corrected_segment
                expected = corrected_expected
                relocation_delta = 3
                correction = "HwordApp 0x411136 indirect-call -> 0x411139 post-call cmp"
            else:
                matches: list[tuple[int, int, dict[str, int]]] = []
                for delta in range(-args.nearby_search, args.nearby_search + 1):
                    candidate_address = requested_target + delta
                    located = locate(candidate_address)
                    if located is None:
                        continue
                    candidate_offset, candidate_segment = located
                    if bytes(blob[candidate_offset:candidate_offset + len(expected)]) == expected:
                        matches.append((candidate_address, candidate_offset,
                                        candidate_segment))
                unique = {(address, offset) for address, offset, _segment in matches}
                if len(unique) != 1:
                    rendered = [f"0x{address:x}" for address, _offset in sorted(unique)]
                    raise SystemExit(
                        "expected prefix " + expected.hex() +
                        f" not uniquely found near 0x{requested_target:x}; "
                        f"requested bytes={requested_bytes.hex()} matches={rendered}")
                target, file_offset = next(iter(unique))
                segment = next(candidate_segment for address, offset, candidate_segment
                               in matches if address == target and offset == file_offset)
                relocation_delta = target - requested_target

    if file_offset + args.signature_length > len(blob):
        raise SystemExit("probe signature extends beyond the ELF file")
    original = bytes(blob[file_offset:file_offset + args.signature_length])
    if original[0] == 0xCC:
        raise SystemExit("target is already an INT3 instruction")
    if expected and not original.startswith(expected):
        raise SystemExit("internal error: relocated target lost expected prefix")

    before = digest(bytes(blob))
    blob[file_offset] = 0xCC
    patched = bytes(blob[file_offset:file_offset + args.signature_length])
    after = digest(bytes(blob))
    args.elf.write_bytes(blob)

    manifest = {
        "schema": 3,
        "kind": "signature-locked-address-int3",
        "label": args.label,
        "path": str(args.elf),
        "elf_type": elf_type,
        "machine": machine,
        "requested_virtual_address": requested_target,
        "virtual_address": target,
        "relocation_delta": relocation_delta,
        "correction": correction,
        "nearby_search": args.nearby_search,
        "requested_expected_prefix_hex": requested_expected.hex(),
        "expected_prefix_hex": expected.hex(),
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
