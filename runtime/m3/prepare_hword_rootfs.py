#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

HWORD_GUEST = Path("/opt/hnc/hoffice11/Bin/hword")
DEFAULT_LIBRARY_DIRS = (
    "/opt/hnc/hoffice11/Bin",
    "/opt/hnc/hoffice11/Bin/qt/lib",
    "/opt/hnc/hoffice11/Bin/Hword",
    "/opt/hnc/hoffice11/Bin/Hwp",
    "/lib/x86_64-linux-gnu",
    "/usr/lib/x86_64-linux-gnu",
    "/lib64",
    "/usr/lib64",
)


def run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    return completed.stdout


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"\x7fELF"
    except OSError:
        return False


def package_library_dirs(root: Path) -> list[Path]:
    result: set[Path] = set()
    for guest in DEFAULT_LIBRARY_DIRS:
        candidate = root / guest.lstrip("/")
        if candidate.is_dir():
            result.add(candidate.resolve())

    bin_root = root / "opt/hnc/hoffice11/Bin"
    if bin_root.is_dir():
        for directory, _subdirectories, files in os.walk(bin_root):
            if any(".so" in name for name in files):
                result.add(Path(directory).resolve())
    return sorted(result)


def parse_interpreter(binary: Path) -> str:
    output = run(["readelf", "-lW", str(binary)])
    match = re.search(r"Requesting program interpreter:\s*([^\]]+)", output)
    if not match:
        raise RuntimeError(f"PT_INTERP not found in {binary}")
    interpreter = match.group(1).strip()
    if not interpreter.startswith("/"):
        raise RuntimeError(f"non-absolute PT_INTERP: {interpreter}")
    return interpreter


def parse_ldd(output: str) -> tuple[set[Path], list[str]]:
    paths: set[Path] = set()
    missing: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("linux-vdso"):
            continue
        if "=> not found" in stripped:
            missing.append(stripped.split("=>", 1)[0].strip())
            continue
        match = re.search(r"=>\s+(/\S+)", stripped)
        if match:
            paths.add(Path(match.group(1)))
            continue
        if stripped.startswith("/"):
            paths.add(Path(stripped.split()[0]))
    return paths, missing


def copy_regular(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source.resolve(), destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generator", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output.resolve()
    generator = args.generator.resolve()
    hword = root / HWORD_GUEST.as_posix().lstrip("/")
    if not is_elf(hword):
        raise RuntimeError(f"HWord ELF not found: {hword}")

    library_dirs = package_library_dirs(root)
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = ":".join(str(path) for path in library_dirs)
    ldd_output = run(["ldd", str(hword)], env=environment)
    dependencies, missing = parse_ldd(ldd_output)
    if missing:
        raise RuntimeError("unresolved HWord dependencies: " + ", ".join(missing))

    interpreter_guest = parse_interpreter(hword)
    interpreter_source = Path(interpreter_guest)
    if not interpreter_source.exists():
        raise RuntimeError(f"host interpreter not found: {interpreter_source}")
    dependencies.add(interpreter_source)

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    objects: dict[str, Path] = {HWORD_GUEST.as_posix(): hword}
    system_sources: dict[str, str] = {}
    root_resolved = root.resolve()
    for dependency in sorted(dependencies, key=str):
        resolved = dependency.resolve()
        try:
            relative = resolved.relative_to(root_resolved)
            guest_path = "/" + relative.as_posix()
            source = resolved
        except ValueError:
            guest_path = dependency.as_posix()
            if not guest_path.startswith("/"):
                raise RuntimeError(f"unexpected dependency path: {dependency}")
            source = resolved
            system_sources[guest_path] = str(resolved)
        objects[guest_path] = source

    objects[interpreter_guest] = interpreter_source.resolve()
    system_sources[interpreter_guest] = str(interpreter_source.resolve())

    for guest_path, source in sorted(objects.items()):
        if not is_elf(source):
            raise RuntimeError(f"dependency is not ELF: {guest_path} -> {source}")
        destination = output / guest_path.lstrip("/")
        copy_regular(source, destination)
        subprocess.run(
            ["python3", str(generator), str(destination)],
            check=True,
            text=True,
        )
        sidecar = Path(str(destination) + ".fspatch")
        if not sidecar.is_file():
            raise RuntimeError(f"FS patch map missing: {sidecar}")

    cache = Path("/etc/ld.so.cache")
    if cache.is_file():
        copy_regular(cache, output / "etc/ld.so.cache")

    metadata = output / ".hrt-m3"
    metadata.mkdir(parents=True)
    (metadata / "ldd.txt").write_text(ldd_output, encoding="utf-8")
    manifest = {
        "program": HWORD_GUEST.as_posix(),
        "interpreter": interpreter_guest,
        "library_path": [
            "/opt/hnc/hoffice11/Bin",
            "/opt/hnc/hoffice11/Bin/qt/lib",
            "/opt/hnc/hoffice11/Bin/Hword",
            "/opt/hnc/hoffice11/Bin/Hwp",
            "/lib/x86_64-linux-gnu",
            "/usr/lib/x86_64-linux-gnu",
        ],
        "objects": sorted(objects),
        "system_sources": system_sources,
    }
    (metadata / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(ldd_output)
    print(f"prepared {len(objects)} ELF objects in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
