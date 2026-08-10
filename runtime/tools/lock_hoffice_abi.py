#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

APPS = {
    "hwp": "/opt/hnc/hoffice11/Bin/hwp",
    "hword": "/opt/hnc/hoffice11/Bin/hword",
    "hcell": "/opt/hnc/hoffice11/Bin/hcl",
    "hshow": "/opt/hnc/hoffice11/Bin/hsl",
}

VERSION_PREFIXES = ("GLIBC_", "GLIBCXX_", "CXXABI_", "GCC_")


def run(*args: str) -> str:
    completed = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return completed.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def parse_header(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, output_key in (
        ("Type", "type"),
        ("Machine", "machine"),
        ("Entry point address", "entry"),
    ):
        match = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", text, re.M)
        result[output_key] = match.group(1) if match else ""
    return result


def parse_dynamic(text: str) -> dict[str, Any]:
    needed = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", text)
    soname = re.findall(r"\(SONAME\).*?\[([^\]]+)\]", text)
    rpath = re.findall(r"\(RPATH\).*?\[([^\]]+)\]", text)
    runpath = re.findall(r"\(RUNPATH\).*?\[([^\]]+)\]", text)
    flags = re.findall(r"\((?:FLAGS|FLAGS_1)\)\s+[^\n]*?\s([^\n]+)$", text, re.M)
    return {
        "needed": needed,
        "soname": soname[0] if soname else "",
        "rpath": rpath,
        "runpath": runpath,
        "flags": flags,
        "bind_now": "BIND_NOW" in text or " NOW " in f" {text} ",
    }


def parse_program_headers(text: str) -> dict[str, Any]:
    interpreter = ""
    match = re.search(r"Requesting program interpreter:\s*([^\]]+)", text)
    if match:
        interpreter = match.group(1).strip()

    stack_match = re.search(
        r"^\s*GNU_STACK\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+([RWE ]+)\s+",
        text,
        re.M,
    )
    stack_flags = "".join((stack_match.group(1) if stack_match else "").split())
    return {
        "interpreter": interpreter,
        "has_pt_dynamic": bool(re.search(r"^\s*DYNAMIC\s", text, re.M)),
        "has_pt_tls": bool(re.search(r"^\s*TLS\s", text, re.M)),
        "has_gnu_relro": bool(re.search(r"^\s*GNU_RELRO\s", text, re.M)),
        "gnu_stack_flags": stack_flags,
        "executable_stack": "E" in stack_flags,
    }


def version_key(version: str) -> tuple[int, ...]:
    numeric = version.split("_", 1)[1]
    parts = []
    for piece in numeric.split("."):
        match = re.match(r"(\d+)", piece)
        parts.append(int(match.group(1)) if match else 0)
    return tuple(parts)


def parse_versions(text: str) -> dict[str, Any]:
    versions: dict[str, list[str]] = {}
    for prefix in VERSION_PREFIXES:
        found = sorted(
            set(re.findall(rf"{re.escape(prefix)}[0-9][0-9A-Za-z.]*", text)),
            key=version_key,
        )
        if found:
            versions[prefix.rstrip("_").lower()] = found
    maxima = {key: values[-1] for key, values in versions.items()}
    return {"all": versions, "max": maxima}


def inspect_elf(path: Path, root: Path) -> dict[str, Any]:
    header_text = run("readelf", "-hW", str(path))
    dynamic_text = run("readelf", "-dW", str(path))
    program_text = run("readelf", "-lW", str(path))
    version_text = run("readelf", "-VW", str(path))
    notes_text = run("readelf", "-nW", str(path))
    reloc_text = run("readelf", "-rW", str(path))

    relative = "/" + path.relative_to(root).as_posix()
    return {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "header": parse_header(header_text),
        "dynamic": parse_dynamic(dynamic_text),
        "program_headers": parse_program_headers(program_text),
        "versions": parse_versions(version_text),
        "gnu_property_x86_isa_1": sorted(
            set(re.findall(r"x86 ISA needed:\s*([^\n]+)", notes_text))
        ),
        "relocation_sections": len(re.findall(r"Relocation section ", reloc_text)),
        "relocation_entries": len(re.findall(r"^\s*[0-9a-f]+\s+", reloc_text, re.M)),
    }


def read_control(control_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    text = (control_dir / "control").read_text(encoding="utf-8", errors="replace")
    current_key = ""
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and current_key:
            result[current_key] += " " + line.strip()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key
        result[key] = value.strip()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    control = read_control(args.control)

    all_elfs = sorted(path for path in root.rglob("*") if path.is_file() and is_elf(path))
    soname_index: dict[str, list[str]] = {}
    basename_index: dict[str, list[str]] = {}
    for path in all_elfs:
        relative = "/" + path.relative_to(root).as_posix()
        basename_index.setdefault(path.name, []).append(relative)
        dynamic = run("readelf", "-dW", str(path))
        parsed = parse_dynamic(dynamic)
        if parsed["soname"]:
            soname_index.setdefault(parsed["soname"], []).append(relative)

    apps: dict[str, Any] = {}
    for name, guest_path in APPS.items():
        path = root / guest_path.lstrip("/")
        if not path.is_file():
            raise SystemExit(f"missing required HOffice executable: {guest_path}")
        details = inspect_elf(path, root)
        resolution: dict[str, dict[str, Any]] = {}
        for needed in details["dynamic"]["needed"]:
            candidates = sorted(set(soname_index.get(needed, []) + basename_index.get(needed, [])))
            resolution[needed] = {
                "packaged_candidates": candidates,
                "resolved_in_package": bool(candidates),
            }
        details["needed_resolution"] = resolution
        apps[name] = details

    report = {
        "schema": 1,
        "source_package": {
            "package": control.get("Package", ""),
            "version": control.get("Version", ""),
            "architecture": control.get("Architecture", ""),
            "depends": control.get("Depends", ""),
            "pre_depends": control.get("Pre-Depends", ""),
        },
        "elf_object_count": len(all_elfs),
        "applications": apps,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# HOffice 11.20.0.1520+h1 ELF ABI lock",
        "",
        f"- Package: `{report['source_package']['package']}`",
        f"- Version: `{report['source_package']['version']}`",
        f"- Architecture: `{report['source_package']['architecture']}`",
        f"- ELF objects in package: **{len(all_elfs)}**",
        "",
        "| App | ELF type | Interpreter | Direct NEEDED | Packaged | System | Max GLIBC | TLS |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for name, details in apps.items():
        resolution = details["needed_resolution"]
        packaged = sum(1 for item in resolution.values() if item["resolved_in_package"])
        system = len(resolution) - packaged
        lines.append(
            "| {name} | `{type}` | `{interp}` | {total} | {packaged} | {system} | `{glibc}` | {tls} |".format(
                name=name,
                type=details["header"]["type"],
                interp=details["program_headers"]["interpreter"],
                total=len(resolution),
                packaged=packaged,
                system=system,
                glibc=details["versions"]["max"].get("glibc", ""),
                tls="yes" if details["program_headers"]["has_pt_tls"] else "no",
            )
        )
    lines.extend(["", "The JSON file is the machine-readable source of truth.", ""])
    args.markdown.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
