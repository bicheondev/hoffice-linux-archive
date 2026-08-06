#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import struct
import subprocess
from pathlib import Path

ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
PT_LOAD = 1


def load_segments(data: bytes) -> list[tuple[int, int, int]]:
    if len(data) < ELF_HEADER.size:
        raise ValueError("short ELF header")
    values = ELF_HEADER.unpack_from(data, 0)
    ident = values[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise ValueError("expected little-endian ELF64")
    phoff = values[5]
    phentsize = values[9]
    phnum = values[10]
    if phentsize != PROGRAM_HEADER.size:
        raise ValueError("unexpected program-header size")
    segments: list[tuple[int, int, int]] = []
    for index in range(phnum):
        offset = phoff + index * phentsize
        if offset + PROGRAM_HEADER.size > len(data):
            raise ValueError("program header outside file")
        p_type, _flags, p_offset, p_vaddr, _paddr, p_filesz, _memsz, _align = (
            PROGRAM_HEADER.unpack_from(data, offset)
        )
        if p_type == PT_LOAD and p_filesz:
            segments.append((p_vaddr, p_vaddr + p_filesz, p_offset))
    return segments


def virtual_to_file(segments: list[tuple[int, int, int]], address: int) -> int:
    for start, end, file_offset in segments:
        if start <= address < end:
            return file_offset + address - start
    raise ValueError(f"instruction address 0x{address:x} is not file-backed")


def write_map(path: Path, header: str, offsets: set[int]) -> None:
    path.write_text(
        f"# {header}\n" + "".join(f"{offset:x}\n" for offset in sorted(offsets)),
        encoding="ascii",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--output", type=Path,
                        help="legacy alias for the FS-prefix map output")
    parser.add_argument("--syscall-output", type=Path)
    args = parser.parse_args()

    binary = args.binary
    fs_output = args.output or Path(str(binary) + ".fspatch")
    syscall_output = args.syscall_output or Path(str(binary) + ".syscallpatch")
    data = binary.read_bytes()
    segments = load_segments(data)
    disassembly = subprocess.run(
        ["objdump", "-d", "-w", "-M", "intel", str(binary)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout

    line_pattern = re.compile(
        r"^\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}(?:\s+|$))+)(.*)$"
    )
    fs_offsets: set[int] = set()
    syscall_offsets: set[int] = set()
    for line in disassembly.splitlines():
        match = line_pattern.match(line)
        if not match:
            continue
        address = int(match.group(1), 16)
        encoded = bytes(int(value, 16) for value in match.group(2).split())
        instruction = match.group(3).strip()
        lowered = instruction.lower()

        if "fs:" in lowered or "%fs:" in lowered:
            try:
                prefix_index = encoded.index(0x64)
            except ValueError:
                pass
            else:
                fs_offsets.add(
                    virtual_to_file(segments, address + prefix_index)
                )

        if re.match(r"^syscall(?:\s|$)", lowered):
            syscall_index = encoded.find(b"\x0f\x05")
            if syscall_index < 0:
                raise ValueError(
                    f"objdump identified syscall without 0f 05 bytes: {line}"
                )
            syscall_offsets.add(
                virtual_to_file(segments, address + syscall_index)
            )

    write_map(
        fs_output,
        "file offsets of x86 FS segment-prefix bytes; M2 rewrites 64 -> 65",
        fs_offsets,
    )
    write_map(
        syscall_output,
        "file offsets of decoded x86 syscall instructions; M2 rewrites 0f05 -> 0f0b",
        syscall_offsets,
    )
    print(
        f"{binary}: {len(fs_offsets)} FS-prefix patches, "
        f"{len(syscall_offsets)} syscall patches -> "
        f"{fs_output}, {syscall_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
