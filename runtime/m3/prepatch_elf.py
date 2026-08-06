#!/usr/bin/env python3
"""Create a shadow-root ELF set patched at verified instruction boundaries.

Rosetta cannot provide a Linux FS base directly.  The runtime therefore uses
GS as the guest TLS segment and traps Linux syscalls through UD2.  A raw byte
scan is unsafe because executable segments can contain embedded constants and
jump tables.  This tool asks GNU objdump for instruction boundaries, validates
each reported byte sequence against the ELF file, and then performs only two
length-preserving transformations:

* Linux ``syscall`` (0f 05) -> ``ud2`` (0f 0b)
* an actual FS segment override (64) -> GS override (65)

It is run against the exact, hash-locked payload copy.  Original distribution
packages remain untouched; the resulting shadow root carries a versioned JSON
marker consumed by the macOS runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ELF_MAGIC = b"\x7fELF"
PT_LOAD = 1
EM_X86_64 = 62
ET_EXEC = 2
ET_DYN = 3

LINE_RE = re.compile(
    r"^\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}(?:\s+|$))+)(.*)$"
)


@dataclass(frozen=True)
class LoadSegment:
    offset: int
    vaddr: int
    filesz: int

    def file_offset(self, address: int, width: int) -> int | None:
        if address < self.vaddr:
            return None
        relative = address - self.vaddr
        if relative > self.filesz or width > self.filesz - relative:
            return None
        return self.offset + relative


@dataclass(frozen=True)
class Patch:
    file_offset: int
    old: int
    new: int
    kind: str
    virtual_address: int


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_load_segments(data: bytes, path: Path) -> list[LoadSegment]:
    if len(data) < 64 or data[:4] != ELF_MAGIC:
        raise ValueError("not ELF")
    if data[4] != 2 or data[5] != 1:
        raise ValueError("not little-endian ELF64")
    (
        _ident,
        elf_type,
        machine,
        _version,
        _entry,
        phoff,
        _shoff,
        _flags,
        _ehsize,
        phentsize,
        phnum,
        _shentsize,
        _shnum,
        _shstrndx,
    ) = struct.unpack_from("<16sHHIQQQIHHHHHH", data, 0)
    if elf_type not in (ET_EXEC, ET_DYN) or machine != EM_X86_64:
        raise ValueError("not x86-64 ET_EXEC/ET_DYN")
    if phentsize < 56 or phnum == 0:
        raise ValueError("invalid program header table")
    if phoff > len(data) or phnum > (len(data) - phoff) // phentsize:
        raise ValueError(f"program header table outside {path}")

    segments: list[LoadSegment] = []
    for index in range(phnum):
        base = phoff + index * phentsize
        p_type, _p_flags, p_offset, p_vaddr, _p_paddr, p_filesz, _p_memsz, _p_align = (
            struct.unpack_from("<IIQQQQQQ", data, base)
        )
        if p_type != PT_LOAD or p_filesz == 0:
            continue
        if p_offset > len(data) or p_filesz > len(data) - p_offset:
            raise ValueError(f"PT_LOAD outside {path}")
        segments.append(LoadSegment(p_offset, p_vaddr, p_filesz))
    if not segments:
        raise ValueError("no loadable file segments")
    return segments


def address_to_offset(
    segments: Iterable[LoadSegment], address: int, width: int
) -> int:
    for segment in segments:
        result = segment.file_offset(address, width)
        if result is not None:
            return result
    raise ValueError(
        f"instruction 0x{address:x}+{width} is outside file-backed PT_LOAD"
    )


def disassemble(path: Path) -> str:
    process = subprocess.run(
        [
            "objdump",
            "-d",
            "-M",
            "intel",
            "--insn-width=16",
            "--",
            os.fspath(path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"objdump failed for {path}: {process.stderr.strip()}"
        )
    return process.stdout


def collect_patches(path: Path, data: bytes) -> list[Patch]:
    segments = parse_load_segments(data, path)
    patches: list[Patch] = []
    seen: set[int] = set()

    for line in disassemble(path).splitlines():
        match = LINE_RE.match(line)
        if match is None:
            continue
        address = int(match.group(1), 16)
        raw = bytes(int(token, 16) for token in match.group(2).split())
        if not raw:
            continue
        assembly = match.group(3).strip().lower()
        base_offset = address_to_offset(segments, address, len(raw))
        if data[base_offset : base_offset + len(raw)] != raw:
            raise RuntimeError(
                f"objdump/file byte mismatch at {path}:0x{address:x}"
            )

        if re.match(r"^syscall(?:\s|$)", assembly):
            try:
                relative = raw.index(b"\x0f\x05")
            except ValueError as error:
                raise RuntimeError(
                    f"syscall mnemonic lacks 0f05 at {path}:0x{address:x}"
                ) from error
            target = base_offset + relative + 1
            if target in seen:
                raise RuntimeError(f"duplicate patch offset {target} in {path}")
            patches.append(Patch(target, 0x05, 0x0B, "syscall", address))
            seen.add(target)

        if "fs:" in assembly:
            try:
                relative = raw.index(0x64)
            except ValueError as error:
                raise RuntimeError(
                    f"FS operand lacks 64 prefix at {path}:0x{address:x}"
                ) from error
            target = base_offset + relative
            if target in seen:
                raise RuntimeError(f"duplicate patch offset {target} in {path}")
            patches.append(Patch(target, 0x64, 0x65, "fs-to-gs", address))
            seen.add(target)

    return sorted(patches, key=lambda patch: patch.file_offset)


def patch_file(path: Path) -> dict[str, object] | None:
    original = path.read_bytes()
    try:
        patches = collect_patches(path, original)
    except ValueError:
        return None
    if not patches:
        return {
            "path": "/" + path.as_posix(),
            "sha256_before": sha256(original),
            "sha256_after": sha256(original),
            "syscalls": 0,
            "fs_to_gs": 0,
            "patches": [],
        }

    modified = bytearray(original)
    for patch in patches:
        actual = modified[patch.file_offset]
        if actual != patch.old:
            raise RuntimeError(
                f"expected {patch.old:02x} at {path}+0x{patch.file_offset:x}, "
                f"found {actual:02x}"
            )
        modified[patch.file_offset] = patch.new

    temporary = path.with_name(path.name + ".hrt-new")
    temporary.write_bytes(modified)
    os.chmod(temporary, path.stat().st_mode & 0o7777)
    os.replace(temporary, path)

    return {
        "path": "/" + path.as_posix(),
        "sha256_before": sha256(original),
        "sha256_after": sha256(modified),
        "syscalls": sum(patch.kind == "syscall" for patch in patches),
        "fs_to_gs": sum(patch.kind == "fs-to-gs" for patch in patches),
        "patches": [
            {
                "file_offset": patch.file_offset,
                "virtual_address": patch.virtual_address,
                "kind": patch.kind,
            }
            for patch in patches
        ],
    }


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            yield path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"root is not a directory: {root}")

    records: list[dict[str, object]] = []
    for path in iter_files(root):
        try:
            if path.read_bytes()[:4] != ELF_MAGIC:
                continue
            record = patch_file(path)
        except Exception as error:  # fail closed with the exact object name
            raise SystemExit(f"prepatch failed for {path}: {error}") from error
        if record is not None:
            record["path"] = "/" + path.relative_to(root).as_posix()
            records.append(record)

    summary = {
        "schema": 1,
        "tool": "runtime/m3/prepatch_elf.py",
        "objects": records,
        "object_count": len(records),
        "syscall_count": sum(int(record["syscalls"]) for record in records),
        "fs_to_gs_count": sum(int(record["fs_to_gs"]) for record in records),
    }
    marker = root / ".hrt-prepatched-v1"
    marker.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"prepatched {summary['object_count']} ELF objects: "
        f"syscalls={summary['syscall_count']} "
        f"fs-to-gs={summary['fs_to_gs_count']}"
    )


if __name__ == "__main__":
    main()
