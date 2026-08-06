#!/usr/bin/env python3
"""Build a minimal guest root for exact HOffice ELF entry points.

The package payload is kept as the source of all HOffice-private objects. Any
remaining Linux ABI libraries are copied from the pinned CI image. Resolution
follows each object's DT_RUNPATH/DT_RPATH before the suite-wide Bin/qt search
paths and finally the host's x86-64 ldconfig cache. Every copied object is
hashed in a manifest so the macOS execution proof can be tied to an exact
closure rather than a mutable host installation.

``--include`` adds ELF roots that are loaded by name or dlopen rather than by a
DT_NEEDED edge. This is required for Qt platform plugins, image-format plugins,
and other runtime-discovered modules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ELF_MAGIC = b"\x7fELF"
NEEDED_RE = re.compile(r"\(NEEDED\).*?Shared library: \[([^\]]+)\]")
PATH_RE = re.compile(
    r"\((?:RPATH|RUNPATH)\).*?Library (?:rpath|runpath): \[([^\]]*)\]"
)
INTERP_RE = re.compile(r"Requesting program interpreter:\s*([^\]]+)\]")
LDCONFIG_RE = re.compile(r"^\s*(\S+)\s+\([^)]*x86-64[^)]*\)\s+=>\s+(\S+)\s*$")


@dataclass(frozen=True)
class PendingObject:
    source: Path
    guest_path: str
    root_reason: str | None = None


def run_text(arguments: list[str]) -> str:
    process = subprocess.run(
        arguments,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(arguments)}\n"
            f"{process.stderr.strip()}"
        )
    return process.stdout


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == ELF_MAGIC
    except OSError:
        return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dynamic_metadata(path: Path) -> tuple[list[str], list[str], str | None]:
    dynamic = run_text(["readelf", "-dW", os.fspath(path)])
    program_headers = run_text(["readelf", "-lW", os.fspath(path)])
    needed = NEEDED_RE.findall(dynamic)
    runtime_paths: list[str] = []
    for entry in PATH_RE.findall(dynamic):
        runtime_paths.extend(component for component in entry.split(":") if component)
    match = INTERP_RE.search(program_headers)
    interpreter = match.group(1).strip() if match else None
    return needed, runtime_paths, interpreter


def parse_ldconfig() -> dict[str, list[Path]]:
    mapping: dict[str, list[Path]] = {}
    output = run_text(["ldconfig", "-p"])
    for line in output.splitlines():
        match = LDCONFIG_RE.match(line)
        if match is None:
            continue
        name, location = match.groups()
        path = Path(location)
        if path.exists() and is_elf(path):
            mapping.setdefault(name, []).append(path)
    return mapping


def package_guest_path(package_root: Path, source: Path) -> str | None:
    try:
        relative = source.relative_to(package_root)
    except ValueError:
        return None
    return "/" + relative.as_posix()


def expand_runtime_path(entry: str, object_source: Path) -> Path:
    expanded = entry.replace("${ORIGIN}", os.fspath(object_source.parent))
    expanded = expanded.replace("$ORIGIN", os.fspath(object_source.parent))
    return Path(expanded)


def choose_resolution(
    name: str,
    object_source: Path,
    runtime_paths: list[str],
    package_root: Path,
    package_globals: list[Path],
    system_globals: list[Path],
    ldconfig: dict[str, list[Path]],
) -> tuple[Path, str]:
    candidates: list[Path] = []
    candidates.extend(expand_runtime_path(entry, object_source) / name
                      for entry in runtime_paths)
    candidates.append(object_source.parent / name)
    candidates.extend(directory / name for directory in package_globals)
    candidates.extend(directory / name for directory in system_globals)
    candidates.extend(ldconfig.get(name, []))

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.absolute()
        if candidate in seen:
            continue
        seen.add(candidate)
        if not candidate.exists() or not is_elf(candidate):
            continue
        guest = package_guest_path(package_root, candidate)
        if guest is None:
            guest = candidate.as_posix()
            if not guest.startswith("/"):
                guest = "/" + guest
        return candidate, guest
    raise FileNotFoundError(
        f"could not resolve {name!r} required by {object_source}"
    )


def copy_object(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    resolved = source.resolve(strict=True)
    shutil.copy2(resolved, destination)
    source_mode = source.stat().st_mode & 0o7777
    os.chmod(destination, source_mode)


def normalize_guest_path(path: str) -> str:
    result = "/" + path.lstrip("/")
    if "/../" in result or result.endswith("/.."):
        raise ValueError(f"unsafe guest path: {path}")
    return result


def package_elf(package_root: Path, guest_path: str) -> Path:
    normalized = normalize_guest_path(guest_path)
    source = package_root / normalized.lstrip("/")
    if not source.is_file() or not is_elf(source):
        raise FileNotFoundError(f"package path is not an ELF file: {source}")
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--program", required=True)
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GUEST_ELF",
        help="additional package ELF root, repeatable (for dlopen plugins)",
    )
    args = parser.parse_args()

    package_root = args.package_root.resolve(strict=True)
    output_root = args.output_root.resolve()
    program_guest = normalize_guest_path(args.program)
    program_source = package_elf(package_root, program_guest)

    include_guests: list[str] = []
    include_sources: list[Path] = []
    for raw_include in args.include:
        guest = normalize_guest_path(raw_include)
        if guest == program_guest or guest in include_guests:
            continue
        include_guests.append(guest)
        include_sources.append(package_elf(package_root, guest))

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    suite_bin = package_root / "opt/hnc/hoffice11/Bin"
    package_globals = [suite_bin, suite_bin / "qt/lib"]
    system_globals = [
        Path("/lib/x86_64-linux-gnu"),
        Path("/usr/lib/x86_64-linux-gnu"),
        Path("/lib64"),
        Path("/usr/lib64"),
    ]
    ldconfig = parse_ldconfig()

    roots = [PendingObject(program_source, program_guest, "program")]
    roots.extend(
        PendingObject(source, guest, "explicit-include")
        for source, guest in zip(include_sources, include_guests, strict=True)
    )
    queue: deque[PendingObject] = deque(roots)
    queued: dict[str, Path] = {
        pending.guest_path: pending.source for pending in roots
    }
    root_reasons: dict[str, str] = {
        pending.guest_path: pending.root_reason
        for pending in roots
        if pending.root_reason is not None
    }
    records: list[dict[str, object]] = []

    while queue:
        pending = queue.popleft()
        source = pending.source
        guest_path = normalize_guest_path(pending.guest_path)
        destination = output_root / guest_path.lstrip("/")
        copy_object(source, destination)
        needed, runtime_paths, interpreter = dynamic_metadata(source)

        resolved_dependencies: list[dict[str, str]] = []
        requests = list(needed)
        if interpreter is not None:
            requests.append(interpreter)

        for request in requests:
            if "/" in request:
                requested_guest = normalize_guest_path(request)
                package_candidate = package_root / requested_guest.lstrip("/")
                host_candidate = Path(requested_guest)
                if package_candidate.exists() and is_elf(package_candidate):
                    dependency_source = package_candidate
                elif host_candidate.exists() and is_elf(host_candidate):
                    dependency_source = host_candidate
                else:
                    raise FileNotFoundError(
                        f"could not resolve absolute ELF {request!r} "
                        f"required by {source}"
                    )
                dependency_guest = requested_guest
            else:
                dependency_source, dependency_guest = choose_resolution(
                    request, source, runtime_paths, package_root,
                    package_globals, system_globals, ldconfig,
                )

            dependency_guest = normalize_guest_path(dependency_guest)
            previous = queued.get(dependency_guest)
            if previous is not None:
                if sha256(previous.resolve(strict=True)) != sha256(
                    dependency_source.resolve(strict=True)
                ):
                    raise RuntimeError(
                        f"guest path collision at {dependency_guest}: "
                        f"{previous} versus {dependency_source}"
                    )
            else:
                queued[dependency_guest] = dependency_source
                queue.append(
                    PendingObject(dependency_source, dependency_guest)
                )
            resolved_dependencies.append(
                {
                    "request": request,
                    "source": os.fspath(dependency_source),
                    "guest_path": dependency_guest,
                }
            )

        records.append(
            {
                "guest_path": guest_path,
                "root_reason": root_reasons.get(guest_path),
                "source": os.fspath(source),
                "sha256": sha256(source.resolve(strict=True)),
                "size": source.resolve(strict=True).stat().st_size,
                "needed": needed,
                "runtime_paths": runtime_paths,
                "interpreter": interpreter,
                "resolved_dependencies": resolved_dependencies,
            }
        )

    for directory in (
        output_root / "tmp",
        output_root / "tmp/hrt-home",
        output_root / "tmp/hrt-runtime",
        output_root / "etc",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    os.chmod(output_root / "tmp/hrt-runtime", 0o700)
    (output_root / "etc/nsswitch.conf").write_text(
        "passwd: files\ngroup: files\nhosts: files dns\n",
        encoding="utf-8",
    )
    (output_root / "etc/hosts").write_text(
        "127.0.0.1 localhost\n::1 localhost\n",
        encoding="utf-8",
    )

    manifest = {
        "schema": 2,
        "program": program_guest,
        "explicit_includes": include_guests,
        "root_count": len(roots),
        "object_count": len(records),
        "total_bytes": sum(int(record["size"]) for record in records),
        "objects": sorted(records, key=lambda record: str(record["guest_path"])),
    }
    manifest_path = output_root / ".hrt-closure-v1.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"closure program={program_guest} roots={manifest['root_count']} "
        f"objects={manifest['object_count']} bytes={manifest['total_bytes']}"
    )


if __name__ == "__main__":
    main()
