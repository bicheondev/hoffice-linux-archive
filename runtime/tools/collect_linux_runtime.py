#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


def run(*args: str) -> str:
    completed = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return completed.stdout


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def dynamic(path: Path) -> tuple[list[str], str, list[str]]:
    text = run("readelf", "-dW", str(path))
    needed = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", text)
    soname_match = re.search(r"\(SONAME\).*?\[([^\]]+)\]", text)
    search = re.findall(r"\((?:RPATH|RUNPATH)\).*?\[([^\]]+)\]", text)
    paths: list[str] = []
    for entry in search:
        paths.extend(piece for piece in entry.split(":") if piece)
    return needed, soname_match.group(1) if soname_match else "", paths


def interpreter(path: Path) -> str:
    text = run("readelf", "-lW", str(path))
    match = re.search(r"Requesting program interpreter:\s*([^\]]+)", text)
    return match.group(1).strip() if match else ""


def ldconfig_index() -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = collections.defaultdict(list)
    text = run("ldconfig", "-p")
    for line in text.splitlines():
        match = re.match(r"\s*(\S+)\s+\([^)]*\)\s+=>\s+(\S+)\s*$", line)
        if not match:
            continue
        candidate = Path(match.group(2))
        if candidate.is_file():
            result[match.group(1)].append(candidate)
    return {key: sorted(values, key=lambda value: str(value)) for key, values in result.items()}


def guest_path(root: Path, host_path: Path) -> str:
    return "/" + host_path.resolve().relative_to(root.resolve()).as_posix()


def copy_system_file(root: Path, source: Path) -> Path:
    absolute = source if source.is_absolute() else source.resolve()
    destination = root / str(absolute).lstrip("/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(absolute.resolve(), destination)
    return destination


def expand_origin(value: str, object_path: Path) -> Path:
    expanded = value.replace("${ORIGIN}", str(object_path.parent))
    expanded = expanded.replace("$ORIGIN", str(object_path.parent))
    return Path(expanded)


def choose_packaged(
    name: str,
    object_path: Path,
    rpaths: Iterable[str],
    by_name: dict[str, list[Path]],
) -> Path | None:
    direct = object_path.parent / name
    if direct.is_file():
        return direct
    for entry in rpaths:
        candidate = expand_origin(entry, object_path) / name
        if candidate.is_file():
            return candidate
    candidates = by_name.get(name, [])
    if not candidates:
        return None
    preferred = sorted(
        candidates,
        key=lambda path: (
            0 if "/opt/hnc/hoffice11/Bin/" in path.as_posix() else 1,
            len(path.as_posix()),
            path.as_posix(),
        ),
    )
    return preferred[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--entry", action="append", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--overlay-list", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    by_name: dict[str, list[Path]] = collections.defaultdict(list)
    packaged_objects: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not is_elf(path):
            continue
        packaged_objects.append(path)
        by_name[path.name].append(path)
        try:
            _, soname, _ = dynamic(path)
        except subprocess.CalledProcessError:
            continue
        if soname:
            by_name[soname].append(path)

    system = ldconfig_index()
    queue: collections.deque[Path] = collections.deque()
    records: dict[str, dict[str, object]] = {}
    missing: dict[str, list[str]] = collections.defaultdict(list)
    copied_system: set[Path] = set()

    for entry in args.entry:
        path = root / entry.lstrip("/")
        if not path.is_file():
            raise SystemExit(f"missing entry ELF: {entry}")
        queue.append(path)
        interp = interpreter(path)
        if interp:
            source = Path(interp)
            if not source.is_file():
                raise SystemExit(f"host interpreter is missing: {interp}")
            copied = copy_system_file(root, source)
            copied_system.add(copied)
            queue.append(copied)

    visited: set[Path] = set()
    while queue:
        current = queue.popleft().resolve()
        if current in visited:
            continue
        visited.add(current)
        needed, soname, rpaths = dynamic(current)
        current_guest = guest_path(root, current)
        record = {
            "path": current_guest,
            "soname": soname,
            "needed": needed,
            "rpaths": rpaths,
            "resolved": {},
        }
        records[current_guest] = record

        for name in needed:
            packaged = choose_packaged(name, current, rpaths, by_name)
            if packaged is not None:
                resolved = packaged.resolve()
                record["resolved"][name] = {
                    "source": "package",
                    "path": guest_path(root, resolved),
                }
                queue.append(resolved)
                continue

            candidates = system.get(name, [])
            if candidates:
                source = candidates[0]
                copied = copy_system_file(root, source)
                copied_system.add(copied)
                record["resolved"][name] = {
                    "source": "host-system",
                    "path": "/" + str(source).lstrip("/"),
                }
                queue.append(copied)
                continue

            missing[name].append(current_guest)
            record["resolved"][name] = {
                "source": "missing",
                "path": "",
            }

    report = {
        "schema": 1,
        "root": str(root),
        "entry_points": args.entry,
        "visited_elf_count": len(visited),
        "packaged_elf_count": len(packaged_objects),
        "copied_system_files": sorted(guest_path(root, path) for path in copied_system),
        "missing": {key: sorted(set(value)) for key, value in sorted(missing.items())},
        "objects": {key: records[key] for key in sorted(records)},
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.overlay_list.write_text(
        "\n".join(sorted(guest_path(root, path).lstrip("/") for path in copied_system)) + "\n",
        encoding="utf-8",
    )

    if missing:
        for name, users in sorted(missing.items()):
            print(f"missing {name}: {', '.join(sorted(set(users)))}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
