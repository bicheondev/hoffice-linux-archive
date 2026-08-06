#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PLUGIN_GUEST = Path(
    "/opt/hnc/hoffice11/Bin/qt/plugins/platforms/libqoffscreen.so"
)
PACKAGE_LIBRARY_DIRS = (
    "/opt/hnc/hoffice11/Bin",
    "/opt/hnc/hoffice11/Bin/qt/lib",
    "/opt/hnc/hoffice11/Bin/Hword",
    "/opt/hnc/hoffice11/Bin/Hwp",
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


def copy_and_patch(source: Path, destination: Path, generator: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source.resolve(), destination)
    subprocess.run(
        ["python3", str(generator), str(destination)],
        check=True,
        text=True,
    )
    for suffix in (".fspatch", ".syscallpatch"):
        sidecar = Path(str(destination) + suffix)
        if not sidecar.is_file():
            raise RuntimeError(f"patch sidecar missing: {sidecar}")


def guest_path_for(dependency: Path, source_root: Path) -> str:
    try:
        relative = dependency.absolute().relative_to(source_root)
    except ValueError:
        guest = dependency.as_posix()
        if not guest.startswith("/"):
            raise RuntimeError(f"non-absolute dependency path: {dependency}")
        return guest
    return "/" + relative.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--generator", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    generator = args.generator.resolve()
    plugin = source_root / PLUGIN_GUEST.as_posix().lstrip("/")
    if not is_elf(plugin):
        raise RuntimeError(f"offscreen QPA plugin not found: {plugin}")

    library_dirs = [
        source_root / path.lstrip("/") for path in PACKAGE_LIBRARY_DIRS
    ]
    library_dirs.extend(
        [Path("/lib/x86_64-linux-gnu"),
         Path("/usr/lib/x86_64-linux-gnu")]
    )
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = ":".join(
        str(path.resolve()) for path in library_dirs if path.is_dir()
    )
    ldd_output = run(["ldd", str(plugin)], env=environment)
    dependencies, missing = parse_ldd(ldd_output)
    if missing:
        raise RuntimeError(
            "unresolved offscreen plugin dependencies: " + ", ".join(missing)
        )

    objects: dict[str, Path] = {PLUGIN_GUEST.as_posix(): plugin}
    for dependency in sorted(dependencies, key=str):
        objects[guest_path_for(dependency, source_root)] = dependency.resolve()

    for guest, source in sorted(objects.items()):
        if not is_elf(source):
            raise RuntimeError(f"dependency is not ELF: {guest} -> {source}")
        destination = output_root / guest.lstrip("/")
        copy_and_patch(source, destination, generator)

    home = output_root / "tmp/hrt-home"
    runtime = output_root / "tmp/hrt-runtime"
    home.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    runtime.chmod(0o700)

    metadata = output_root / ".hrt-m4"
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / "offscreen-ldd.txt").write_text(ldd_output, encoding="utf-8")
    (metadata / "manifest.json").write_text(
        json.dumps(
            {
                "platform": "offscreen",
                "plugin": PLUGIN_GUEST.as_posix(),
                "objects": sorted(objects),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(ldd_output)
    print(f"added {len(objects)} offscreen QPA ELF objects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
