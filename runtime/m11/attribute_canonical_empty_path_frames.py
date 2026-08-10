#!/usr/bin/env python3
"""Attribute canonical HWord empty-path return frames on a Linux analysis host.

The macOS compatibility replay emits one ``HRT M11 FRAMECTX`` record after each
traced ``open`` boundary.  Earlier diagnostics established that arbitrary stack
words are not trustworthy callers; this tool consumes only the bounded saved
RBP/return chain and maps those file offsets back to the exact ELF objects.

Two subcommands are provided:

``list-objects``
    Parse the canonical frame summary and emit the exact guest object paths that
    must be extracted from the prepared HWord root.

``analyze``
    Resolve each unique HOffice return frame to its PT_LOAD segment and virtual
    address, disassemble a focused window, identify the instruction immediately
    preceding the return address, and classify whether the frame is directly
    after a call such as ``fopen``.  The original summary is not modified.

The implementation is deterministic, bounded, and fail-closed.  It supports
only little-endian ELF64 because the locked HWord guest is x86-64 ELF64.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


HOFFICE_PREFIX = "/opt/hnc/hoffice11/"
FRAME_COUNT_RE = re.compile(r"\bcount=(\d+)")
FRAME_VALUE_RE = re.compile(r"\bframe(\d+)-return=(0x[0-9a-fA-F]+)")
FRAME_OFFSET_RE = re.compile(
    r"\bframe(\d+)-return-file-offset=(0x[0-9a-fA-F]+)"
)
FRAME_OBJECT_RE = re.compile(
    r"\bframe(?P<index>\d+)-return-object=(?P<object>.*?)"
    r"(?=\s+frame\d+(?:-rbp=|-saved=|-return=|-return-object="
    r"|-return-file-offset=)|$)"
)
INSTRUCTION_RE = re.compile(
    r"^\s*(?P<address>[0-9a-fA-F]+):\s+"
    r"(?P<bytes>(?:[0-9a-fA-F]{2}\s+)+)"
    r"(?P<mnemonic>[A-Za-z][A-Za-z0-9_.]*)"
    r"(?:\s+(?P<operand>.*?))?\s*$"
)
SYMBOL_RE = re.compile(
    r"^\s*\d+:\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+"
    r"(\S+)\s+(\S+)\s+(\S+)\s+(.*)$"
)


@dataclass(frozen=True)
class Segment:
    index: int
    flags: int
    file_offset: int
    virtual_address: int
    file_size: int
    memory_size: int
    alignment: int

    @property
    def executable(self) -> bool:
        return bool(self.flags & 1)

    def contains_file_offset(self, value: int) -> bool:
        return self.file_offset <= value < self.file_offset + self.file_size

    def contains_virtual_address(self, value: int) -> bool:
        return (
            self.virtual_address
            <= value
            < self.virtual_address + self.memory_size
        )

    def file_to_virtual(self, value: int) -> int:
        if not self.contains_file_offset(value):
            raise ValueError("file offset is outside segment")
        return self.virtual_address + value - self.file_offset

    def virtual_to_file(self, value: int) -> int | None:
        if not self.contains_virtual_address(value):
            return None
        delta = value - self.virtual_address
        if delta >= self.file_size:
            return None
        return self.file_offset + delta

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "flags": self.flags,
            "file_offset": self.file_offset,
            "virtual_address": self.virtual_address,
            "file_size": self.file_size,
            "memory_size": self.memory_size,
            "alignment": self.alignment,
            "executable": self.executable,
        }


@dataclass(frozen=True)
class Instruction:
    address: int
    bytes_hex: str
    size: int
    mnemonic: str
    operand: str
    line: str

    @property
    def end_address(self) -> int:
        return self.address + self.size

    def as_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "bytes_hex": self.bytes_hex,
            "size": self.size,
            "mnemonic": self.mnemonic,
            "operand": self.operand,
            "end_address": self.end_address,
            "line": self.line,
        }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"could not read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"expected a JSON object in {path}")
    return value


def parse_frame_context(line: str) -> list[dict[str, Any]]:
    if not line.startswith("HRT M11 FRAMECTX:"):
        return []
    values = {int(index): value for index, value in FRAME_VALUE_RE.findall(line)}
    offsets = {
        int(index): value for index, value in FRAME_OFFSET_RE.findall(line)
    }
    objects = {
        int(match.group("index")): match.group("object").strip()
        for match in FRAME_OBJECT_RE.finditer(line)
    }
    count_match = FRAME_COUNT_RE.search(line)
    observed_indices = set(values) | set(offsets) | set(objects)
    count = int(count_match.group(1)) if count_match else 0
    if observed_indices:
        count = max(count, max(observed_indices) + 1)
    frames: list[dict[str, Any]] = []
    for index in range(count):
        object_name = objects.get(index)
        if object_name and object_name.startswith("(unmapped)"):
            object_name = "(unmapped)"
        frames.append(
            {
                "index": index,
                "value": values.get(index),
                "object": object_name,
                "file_offset": offsets.get(index),
            }
        )
    return frames


def canonical_records(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw_records = summary.get("empty_path_records")
    if not isinstance(raw_records, list):
        raise SystemExit("summary has no empty_path_records array")
    records: list[dict[str, Any]] = []
    for record_index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            continue
        frame_line = raw.get("frame_context")
        frames = parse_frame_context(frame_line) if isinstance(frame_line, str) else []
        if not frames:
            fallback = raw.get("frames")
            if isinstance(fallback, list):
                frames = [item for item in fallback if isinstance(item, dict)]
        records.append(
            {
                "record_index": record_index,
                "open": raw.get("open"),
                "open_context": raw.get("open_context"),
                "frame_context": frame_line,
                "frames": frames,
                "first_hoffice_frame": next(
                    (
                        frame
                        for frame in frames
                        if isinstance(frame.get("object"), str)
                        and frame["object"].startswith(HOFFICE_PREFIX)
                    ),
                    None,
                ),
            }
        )
    if not records:
        raise SystemExit("summary contains no canonical empty-path records")
    return records


def hword_requests(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for record in records:
        for frame in record["frames"]:
            object_name = frame.get("object")
            offset_text = frame.get("file_offset")
            if (
                not isinstance(object_name, str)
                or not object_name.startswith(HOFFICE_PREFIX)
                or not isinstance(offset_text, str)
            ):
                continue
            try:
                file_offset = int(offset_text, 0)
            except ValueError:
                continue
            key = (object_name, file_offset)
            item = grouped.setdefault(
                key,
                {
                    "guest_path": object_name,
                    "file_offset": file_offset,
                    "record_indices": [],
                    "frame_indices": [],
                    "occurrence_count": 0,
                },
            )
            item["record_indices"].append(record["record_index"])
            item["frame_indices"].append(frame.get("index"))
            item["occurrence_count"] += 1
    requests = sorted(
        grouped.values(),
        key=lambda item: (item["guest_path"], item["file_offset"]),
    )
    if not requests:
        raise SystemExit("canonical records contain no HOffice frame offsets")
    return requests


def parse_elf64_segments(blob: bytes, path: Path) -> list[Segment]:
    if len(blob) < 64:
        raise SystemExit(f"ELF is too short: {path}")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", blob, 0)
    ident = header[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise SystemExit(f"expected little-endian ELF64: {path}")
    phoff = header[5]
    phentsize = header[9]
    phnum = header[10]
    if phentsize < 56:
        raise SystemExit(f"unexpected ELF64 program header size {phentsize}: {path}")
    segments: list[Segment] = []
    for index in range(phnum):
        offset = phoff + index * phentsize
        if offset + 56 > len(blob):
            raise SystemExit(f"truncated program header {index}: {path}")
        p_type, flags, file_offset, virtual_address, _physical, file_size, \
            memory_size, alignment = struct.unpack_from("<IIQQQQQQ", blob, offset)
        if p_type == 1:  # PT_LOAD
            segments.append(
                Segment(
                    index=index,
                    flags=flags,
                    file_offset=file_offset,
                    virtual_address=virtual_address,
                    file_size=file_size,
                    memory_size=memory_size,
                    alignment=alignment,
                )
            )
    if not segments:
        raise SystemExit(f"ELF contains no PT_LOAD segment: {path}")
    return segments


def run_text(command: list[str]) -> str:
    try:
        return subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout
    except FileNotFoundError as error:
        raise SystemExit(f"required analysis tool is missing: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"analysis command failed ({error.returncode}): {' '.join(command)}\n"
            f"{error.stdout[-4000:] if error.stdout else ''}"
        ) from error


def read_symbols(path: Path) -> list[dict[str, Any]]:
    output = run_text(["readelf", "-W", "-s", "--demangle", str(path)])
    symbols: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = SYMBOL_RE.match(line)
        if not match:
            continue
        value = int(match.group(1), 16)
        size = int(match.group(2))
        name = match.group(7).strip()
        if value == 0 or not name:
            continue
        symbols.append(
            {
                "value": value,
                "size": size,
                "type": match.group(3),
                "binding": match.group(4),
                "visibility": match.group(5),
                "section": match.group(6),
                "name": name,
            }
        )
    return symbols


def nearest_symbol(
    symbols: list[dict[str, Any]], virtual_address: int
) -> dict[str, Any] | None:
    containing = [
        symbol
        for symbol in symbols
        if symbol["size"] > 0
        and symbol["value"] <= virtual_address
        < symbol["value"] + symbol["size"]
    ]
    candidates = containing or [
        symbol for symbol in symbols if symbol["value"] <= virtual_address
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda symbol: symbol["value"])


def parse_instructions(output: str) -> list[Instruction]:
    instructions: list[Instruction] = []
    for line in output.splitlines():
        match = INSTRUCTION_RE.match(line)
        if not match:
            continue
        byte_values = match.group("bytes").split()
        instructions.append(
            Instruction(
                address=int(match.group("address"), 16),
                bytes_hex="".join(byte_values).lower(),
                size=len(byte_values),
                mnemonic=match.group("mnemonic").lower(),
                operand=(match.group("operand") or "").strip(),
                line=line.strip(),
            )
        )
    return instructions


def classify_predecessor(instruction: Instruction | None) -> str:
    if instruction is None:
        return "NO_PRECEDING_INSTRUCTION"
    if not instruction.mnemonic.startswith("call"):
        return "NOT_IMMEDIATE_POST_CALL"
    operand = instruction.operand.lower()
    categories = (
        ("fopen", "POST_FOPEN_CALL"),
        ("open", "POST_OPEN_CALL"),
        ("stat", "POST_STAT_CALL"),
        ("access", "POST_ACCESS_CALL"),
        ("read", "POST_READ_CALL"),
        ("write", "POST_WRITE_CALL"),
        ("sendfile", "POST_SENDFILE_CALL"),
        ("operator new", "POST_OPERATOR_NEW_CALL"),
    )
    for needle, classification in categories:
        if needle in operand:
            return classification
    return "POST_CALL"


def direct_rel32_target(
    blob: bytes,
    file_offset: int,
    return_virtual_address: int,
) -> int | None:
    if file_offset < 5 or blob[file_offset - 5] != 0xE8:
        return None
    displacement = struct.unpack_from("<i", blob, file_offset - 4)[0]
    return return_virtual_address + displacement


def target_symbol_from_operand(operand: str) -> str | None:
    match = re.search(r"<([^>]+)>", operand)
    return match.group(1) if match else None


def safe_name(path: str, file_offset: int) -> str:
    stem = path.strip("/").replace("/", "_").replace(".", "_")
    return f"{stem}-file-0x{file_offset:x}"


def analyze_request(
    request: dict[str, Any],
    root: Path,
    disassembly_dir: Path,
    cache: dict[str, tuple[bytes, list[Segment], list[dict[str, Any]]]],
) -> dict[str, Any]:
    guest_path = request["guest_path"]
    file_offset = request["file_offset"]
    host_path = root / guest_path.lstrip("/")
    base: dict[str, Any] = dict(request)
    base["host_path"] = str(host_path)
    if not host_path.is_file():
        base["classification"] = "OBJECT_NOT_EXTRACTED"
        return base

    cache_key = str(host_path)
    if cache_key not in cache:
        blob = host_path.read_bytes()
        cache[cache_key] = (
            blob,
            parse_elf64_segments(blob, host_path),
            read_symbols(host_path),
        )
    blob, segments, symbols = cache[cache_key]
    base["object_sha256"] = hashlib.sha256(blob).hexdigest()
    base["object_size"] = len(blob)
    if file_offset < 0 or file_offset >= len(blob):
        base["classification"] = "FILE_OFFSET_OUT_OF_RANGE"
        return base
    segment = next(
        (item for item in segments if item.contains_file_offset(file_offset)),
        None,
    )
    if segment is None:
        base["classification"] = "OUTSIDE_PT_LOAD"
        return base

    virtual_address = segment.file_to_virtual(file_offset)
    base["virtual_address"] = virtual_address
    base["segment"] = segment.as_dict()
    symbol = nearest_symbol(symbols, virtual_address)
    base["nearest_symbol"] = symbol
    base["offset_from_nearest_symbol"] = (
        virtual_address - symbol["value"] if symbol else None
    )
    base["bytes_before"] = blob[max(0, file_offset - 64) : file_offset].hex()
    base["bytes_at_and_after"] = blob[
        file_offset : min(len(blob), file_offset + 128)
    ].hex()

    start = max(segment.virtual_address, virtual_address - 0x500)
    stop = min(
        segment.virtual_address + segment.memory_size,
        virtual_address + 0x700,
    )
    disassembly = run_text(
        [
            "objdump",
            "-dC",
            "-Mintel",
            f"--start-address={start}",
            f"--stop-address={stop}",
            str(host_path),
        ]
    )
    filename = safe_name(guest_path, file_offset) + ".disassembly.txt"
    disassembly_dir.mkdir(parents=True, exist_ok=True)
    disassembly_path = disassembly_dir / filename
    disassembly_path.write_text(disassembly, encoding="utf-8")
    base["disassembly_path"] = str(disassembly_path)

    instructions = parse_instructions(disassembly)
    exact_predecessor = next(
        (
            instruction
            for instruction in reversed(instructions)
            if instruction.end_address == virtual_address
        ),
        None,
    )
    nearest_predecessor = next(
        (
            instruction
            for instruction in reversed(instructions)
            if instruction.address < virtual_address
        ),
        None,
    )
    predecessor = exact_predecessor or nearest_predecessor
    base["immediate_predecessor"] = predecessor.as_dict() if predecessor else None
    base["predecessor_ends_at_return"] = exact_predecessor is not None
    base["callsite_classification"] = classify_predecessor(exact_predecessor)
    base["call_target_symbol"] = (
        target_symbol_from_operand(exact_predecessor.operand)
        if exact_predecessor and exact_predecessor.mnemonic.startswith("call")
        else None
    )

    rel32_target = direct_rel32_target(blob, file_offset, virtual_address)
    base["direct_rel32_target_virtual_address"] = rel32_target
    if rel32_target is not None:
        target_segment = next(
            (item for item in segments if item.contains_virtual_address(rel32_target)),
            None,
        )
        base["direct_rel32_target_file_offset"] = (
            target_segment.virtual_to_file(rel32_target)
            if target_segment
            else None
        )
        target_symbol = nearest_symbol(symbols, rel32_target)
        base["direct_rel32_target_nearest_symbol"] = target_symbol
        base["direct_rel32_target_offset_from_symbol"] = (
            rel32_target - target_symbol["value"] if target_symbol else None
        )

    base["classification"] = (
        base["callsite_classification"]
        if segment.executable
        else "NON_EXECUTABLE_SEGMENT"
    )
    base["confidence"] = (
        "HIGH"
        if segment.executable and exact_predecessor is not None
        else "MEDIUM"
        if segment.executable
        else "LOW"
    )
    return base


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# HWord canonical empty-path static attribution",
        "",
        f"- Source workflow run: `{payload.get('source_workflow_run')}`",
        f"- Source host run: `{payload.get('source_host_run')}`",
        f"- Empty-path records: `{payload['empty_path_record_count']}`",
        f"- Unique HOffice frame targets: `{len(payload['targets'])}`",
        "",
        "| object | file offset | occurrences | classification | predecessor | call target | confidence |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for target in payload["targets"]:
        predecessor = target.get("immediate_predecessor") or {}
        predecessor_text = (
            f"`{predecessor.get('mnemonic', '')} "
            f"{predecessor.get('operand', '')}`".strip()
            if predecessor
            else "—"
        )
        call_target = target.get("call_target_symbol") or "—"
        lines.append(
            f"| `{target['guest_path']}` | `0x{target['file_offset']:x}` | "
            f"{target['occurrence_count']} | `{target.get('classification')}` | "
            f"{predecessor_text} | `{call_target}` | "
            f"`{target.get('confidence', 'UNKNOWN')}` |"
        )

    lines.extend(["", "## Per-record canonical HOffice frame", ""])
    for record in payload["records"]:
        frame = record.get("first_hoffice_frame")
        if frame:
            lines.append(
                f"- Record `{record['record_index']}` → "
                f"`{frame.get('object')}` file `{frame.get('file_offset')}`"
            )
        else:
            lines.append(f"- Record `{record['record_index']}` → none")

    lines.extend(["", "## Interpretation", ""])
    classes = Counter(
        target.get("classification", "UNKNOWN") for target in payload["targets"]
    )
    for classification, count in sorted(classes.items()):
        lines.append(f"- `{classification}`: `{count}` unique target(s)")
    repeated = [
        target for target in payload["targets"] if target["occurrence_count"] > 1
    ]
    if repeated:
        lines.append(
            "- Repeated canonical targets: "
            + ", ".join(
                f"`{item['guest_path']}+0x{item['file_offset']:x}` "
                f"({item['occurrence_count']} records)"
                for item in repeated
            )
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def command_list_objects(args: argparse.Namespace) -> None:
    summary = load_json(args.summary)
    records = canonical_records(summary)
    requests = hword_requests(records)
    paths = sorted({request["guest_path"] for request in requests})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join("." + value + "\n" for value in paths),
        encoding="utf-8",
    )
    print(json.dumps({"objects": paths}, ensure_ascii=False, indent=2))


def command_analyze(args: argparse.Namespace) -> None:
    summary = load_json(args.summary)
    records = canonical_records(summary)
    requests = hword_requests(records)
    cache: dict[str, tuple[bytes, list[Segment], list[dict[str, Any]]]] = {}
    targets = [
        analyze_request(
            request,
            args.root,
            args.disassembly_dir,
            cache,
        )
        for request in requests
    ]
    payload = {
        "schema": 2,
        "source_summary": str(args.summary),
        "source_workflow_run": summary.get("workflow_run"),
        "source_commit": summary.get("commit"),
        "source_host_run": summary.get("host_run"),
        "empty_path_record_count": len(records),
        "records": records,
        "targets": targets,
        "target_classification_counts": dict(
            Counter(target.get("classification", "UNKNOWN") for target in targets)
        ),
        "object_sha256": {
            guest_path: hashlib.sha256(blob).hexdigest()
            for guest_path, (blob, _segments, _symbols) in cache.items()
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown(payload, args.output_markdown)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    unresolved = [
        target
        for target in targets
        if target.get("classification")
        in {"OBJECT_NOT_EXTRACTED", "FILE_OFFSET_OUT_OF_RANGE", "OUTSIDE_PT_LOAD"}
    ]
    if unresolved:
        raise SystemExit(
            "one or more canonical HOffice frame targets could not be resolved"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-objects")
    list_parser.add_argument("--summary", type=Path, required=True)
    list_parser.add_argument("--output", type=Path, required=True)
    list_parser.set_defaults(entry=command_list_objects)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--summary", type=Path, required=True)
    analyze_parser.add_argument("--root", type=Path, required=True)
    analyze_parser.add_argument("--output-json", type=Path, required=True)
    analyze_parser.add_argument("--output-markdown", type=Path, required=True)
    analyze_parser.add_argument("--disassembly-dir", type=Path, required=True)
    analyze_parser.set_defaults(entry=command_analyze)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.entry(args)


if __name__ == "__main__":
    main()
