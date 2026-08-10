#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
from collections import deque

NEEDED_RE = re.compile(r"Shared library: \[([^\]]+)\]")
PATH_RE = re.compile(r"\((?:RPATH|RUNPATH)\).*?\[([^\]]*)\]")
INTERP_RE = re.compile(r"Requesting program interpreter:\s*([^\]]+)\]")

KNOWN_GUEST_DIRS = [
    "/opt/hnc/hoffice11/Bin",
    "/opt/hnc/hoffice11/Bin/qt/lib",
    "/opt/hnc/hoffice11/Bin/qt/plugins",
    "/lib64",
    "/lib/x86_64-linux-gnu",
    "/usr/lib/x86_64-linux-gnu",
    "/usr/local/lib",
    "/lib",
    "/usr/lib",
]


def run_text(*args: str) -> str:
    completed = subprocess.run(
        args,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def normalize_guest(path: str) -> str:
    normalized = pathlib.PurePosixPath(path)
    if not normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"unsafe guest path: {path}")
    return str(normalized)


def dynamic_metadata(host_path: pathlib.Path) -> tuple[list[str], list[str], str | None]:
    dynamic = run_text("readelf", "-dW", str(host_path))
    needed = NEEDED_RE.findall(dynamic)
    paths: list[str] = []
    for raw in PATH_RE.findall(dynamic):
        paths.extend(part for part in raw.split(":") if part)
    program_headers = run_text("readelf", "-lW", str(host_path))
    match = INTERP_RE.search(program_headers)
    interpreter = match.group(1).strip() if match else None
    return needed, paths, interpreter


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def host_source_for_guest(source_root: pathlib.Path, guest: str) -> pathlib.Path | None:
    packaged = source_root / guest.lstrip("/")
    if packaged.exists():
        return packaged.resolve()
    host = pathlib.Path(guest)
    if host.exists():
        return host.resolve()
    return None


def build_payload_index(source_root: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    index: dict[str, list[pathlib.Path]] = {}
    base = source_root / "opt/hnc/hoffice11/Bin"
    if not base.exists():
        return index
    for path in base.rglob("*"):
        if path.is_file() or path.is_symlink():
            index.setdefault(path.name, []).append(path)
    for values in index.values():
        values.sort(key=lambda p: (len(p.parts), str(p)))
    return index


def build_ldconfig_index() -> dict[str, list[pathlib.Path]]:
    index: dict[str, list[pathlib.Path]] = {}
    text = run_text("ldconfig", "-p")
    for line in text.splitlines():
        if "=>" not in line:
            continue
        left, right = line.split("=>", 1)
        name = left.strip().split()[0]
        path = pathlib.Path(right.strip())
        if path.exists():
            index.setdefault(name, []).append(path)
    return index


def expand_search_path(raw: str, origin: str) -> str | None:
    value = raw.replace("${ORIGIN}", origin).replace("$ORIGIN", origin)
    if not value.startswith("/"):
        value = str(pathlib.PurePosixPath(origin) / value)
    try:
        return normalize_guest(value)
    except ValueError:
        return None


def locate_needed(
    name: str,
    origin: str,
    dynamic_paths: list[str],
    source_root: pathlib.Path,
    payload_index: dict[str, list[pathlib.Path]],
    ldconfig_index: dict[str, list[pathlib.Path]],
) -> tuple[str, pathlib.Path] | None:
    guest_dirs: list[str] = []
    for raw in dynamic_paths:
        expanded = expand_search_path(raw, origin)
        if expanded and expanded not in guest_dirs:
            guest_dirs.append(expanded)
    for directory in [origin, *KNOWN_GUEST_DIRS]:
        if directory not in guest_dirs:
            guest_dirs.append(directory)

    for directory in guest_dirs:
        guest = normalize_guest(str(pathlib.PurePosixPath(directory) / name))
        packaged = source_root / guest.lstrip("/")
        if packaged.exists():
            return guest, packaged.resolve()
        host = pathlib.Path(guest)
        if host.exists():
            return guest, host.resolve()

    for packaged in payload_index.get(name, []):
        guest = "/" + packaged.relative_to(source_root).as_posix()
        return normalize_guest(guest), packaged.resolve()

    for host in ldconfig_index.get(name, []):
        return normalize_guest(str(host)), host.resolve()
    return None


def copy_object(source: pathlib.Path, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    mode = source.stat().st_mode
    os.chmod(destination, stat.S_IMODE(mode) | stat.S_IRUSR)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=pathlib.Path)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output-root", required=True, type=pathlib.Path)
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    target = normalize_guest(args.target)
    target_source = host_source_for_guest(source_root, target)
    if target_source is None:
        raise SystemExit(f"target not found: {target}")

    payload_index = build_payload_index(source_root)
    ldconfig_index = build_ldconfig_index()
    queue: deque[tuple[str, pathlib.Path]] = deque([(target, target_source)])
    queued = {target}
    copied: dict[str, dict[str, object]] = {}
    unresolved: list[dict[str, str]] = []
    interpreter_path: str | None = None

    while queue:
        guest, source = queue.popleft()
        destination = output_root / guest.lstrip("/")
        copy_object(source, destination)
        needed, dynamic_paths, interpreter = dynamic_metadata(source)
        copied[guest] = {
            "source": str(source),
            "size": source.stat().st_size,
            "sha256": sha256(source),
            "needed": needed,
            "search_paths": dynamic_paths,
        }
        origin = str(pathlib.PurePosixPath(guest).parent)

        if interpreter is not None:
            interpreter = normalize_guest(interpreter)
            if guest == target:
                interpreter_path = interpreter
            if interpreter not in queued:
                interpreter_source = host_source_for_guest(source_root, interpreter)
                if interpreter_source is None:
                    unresolved.append({"owner": guest, "needed": interpreter})
                else:
                    queued.add(interpreter)
                    queue.append((interpreter, interpreter_source))

        for name in needed:
            located = locate_needed(
                name, origin, dynamic_paths, source_root,
                payload_index, ldconfig_index,
            )
            if located is None:
                unresolved.append({"owner": guest, "needed": name})
                continue
            dependency_guest, dependency_source = located
            if dependency_guest in queued:
                continue
            queued.add(dependency_guest)
            queue.append((dependency_guest, dependency_source))

    total_size = sum(int(item["size"]) for item in copied.values())
    manifest = {
        "schema": 1,
        "target": target,
        "interpreter": interpreter_path,
        "object_count": len(copied),
        "total_size": total_size,
        "objects": dict(sorted(copied.items())),
        "unresolved": unresolved,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "target": target,
        "interpreter": interpreter_path,
        "object_count": len(copied),
        "total_size": total_size,
        "unresolved": unresolved,
    }, ensure_ascii=False, indent=2))
    if interpreter_path is None:
        print("target has no PT_INTERP", file=sys.stderr)
        return 1
    if unresolved:
        print("unresolved ELF dependencies remain", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
