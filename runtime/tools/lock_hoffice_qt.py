#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def run(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        args,
        check=check,
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


def header(path: Path) -> dict[str, str]:
    text = run("readelf", "-hW", str(path))
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"\s*([^:]+):\s*(.*)$", line)
        if match:
            result[match.group(1).strip().lower().replace(" ", "_")] = (
                match.group(2).strip()
            )
    return result


def dynamic(path: Path) -> dict[str, Any]:
    text = run("readelf", "-dW", str(path), check=False)
    needed = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", text)
    soname = re.findall(r"\(SONAME\).*?\[([^\]]+)\]", text)
    rpath = re.findall(r"\((?:RPATH|RUNPATH)\).*?\[([^\]]+)\]", text)
    return {
        "needed": needed,
        "soname": soname[0] if soname else "",
        "rpath_runpath": rpath,
    }


def versions(path: Path) -> dict[str, list[str]]:
    text = run("readelf", "-VW", str(path), check=False)
    namespaces = {
        "qt": r"\bQt_[0-9][A-Za-z0-9_.-]*",
        "glibc": r"\bGLIBC_[0-9][0-9.]*",
        "glibcxx": r"\bGLIBCXX_[0-9][0-9.]*",
        "cxxabi": r"\bCXXABI_[0-9][0-9.]*",
    }
    return {
        name: sorted(set(re.findall(pattern, text)))
        for name, pattern in namespaces.items()
    }


def exported_qt_symbols(path: Path) -> list[str]:
    text = run("readelf", "-WsW", str(path), check=False)
    symbols: set[str] = set()
    for line in text.splitlines():
        if " GLOBAL " not in line or " UND " in line:
            continue
        fields = line.split()
        if not fields:
            continue
        name = fields[-1].split("@", 1)[0]
        if name.startswith(("_ZN2Qt", "_ZN15QGuiApplication", "qt_")):
            symbols.add(name)
    return sorted(symbols)


def selected_strings(path: Path) -> list[str]:
    text = run("strings", "-a", "-n", "4", str(path), check=False)
    patterns = re.compile(
        r"(?i)(qt\s*5\.|qpa|platforms?|xcb|offscreen|minimal|egl|glx|"
        r"wayland|fontconfig|freetype|inputcontext|clipboard|linuxfb)"
    )
    values: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) <= 240 and patterns.search(stripped):
            values.append(stripped)
    return sorted(set(values))[:400]


def sections(path: Path) -> list[dict[str, Any]]:
    text = run("readelf", "-SW", str(path), check=False)
    result: list[dict[str, Any]] = []
    pattern = re.compile(
        r"\[\s*(\d+)\]\s+(\S+)\s+(\S+)\s+([0-9a-fA-F]+)\s+"
        r"([0-9a-fA-F]+)\s+([0-9a-fA-F]+)"
    )
    for line in text.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        name = match.group(2)
        if name in {".qtmetadata", ".note.qt.metadata", ".rodata", ".text"}:
            result.append({
                "index": int(match.group(1)),
                "name": name,
                "type": match.group(3),
                "address": "0x" + match.group(4).lower(),
                "offset": "0x" + match.group(5).lower(),
                "size": int(match.group(6), 16),
            })
    return result


def describe(root: Path, path: Path) -> dict[str, Any]:
    relative = "/" + path.relative_to(root).as_posix()
    return {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "file": run("file", "-b", str(path)).strip(),
        "header": header(path),
        "dynamic": dynamic(path),
        "versions": versions(path),
        "selected_export_count": len(exported_qt_symbols(path)),
        "selected_exports": exported_qt_symbols(path)[:500],
        "metadata_sections": sections(path),
        "diagnostic_strings": selected_strings(path),
    }


def parse_control(control: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    current = ""
    for line in (control / "control").read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if line.startswith((" ", "\t")) and current:
            fields[current] += " " + line.strip()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current = key.strip()
        fields[current] = value.strip()
    return fields


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    control = parse_control(args.control)
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not is_elf(path):
            continue
        relative = path.relative_to(root).as_posix().lower()
        name = path.name.lower()
        if (
            "/qt/" in "/" + relative
            or "/plugins/" in "/" + relative
            or name.startswith("libqt5")
            or name.startswith("libq") and name.endswith(".so")
        ):
            candidates.append(path)

    core_names = {
        "libQt5Core.so.5",
        "libQt5Gui.so.5",
        "libQt5Widgets.so.5",
    }
    core = [path for path in candidates if path.name in core_names]
    platforms = [
        path for path in candidates
        if "/platforms/" in "/" + path.relative_to(root).as_posix().lower()
    ]
    platform_themes = [
        path for path in candidates
        if "/platformthemes/" in "/" + path.relative_to(root).as_posix().lower()
    ]
    input_contexts = [
        path for path in candidates
        if "/platforminputcontexts/" in "/" + path.relative_to(root).as_posix().lower()
    ]

    objects = {str(path.relative_to(root)): describe(root, path) for path in candidates}
    report = {
        "schema": 1,
        "source_package": {
            "package": control.get("Package", ""),
            "version": control.get("Version", ""),
            "architecture": control.get("Architecture", ""),
        },
        "summary": {
            "qt_related_elf_count": len(candidates),
            "core_library_count": len(core),
            "platform_plugin_count": len(platforms),
            "platform_theme_count": len(platform_themes),
            "input_context_count": len(input_contexts),
        },
        "core_libraries": ["/" + path.relative_to(root).as_posix() for path in core],
        "platform_plugins": ["/" + path.relative_to(root).as_posix() for path in platforms],
        "platform_themes": ["/" + path.relative_to(root).as_posix() for path in platform_themes],
        "platform_input_contexts": ["/" + path.relative_to(root).as_posix() for path in input_contexts],
        "objects": objects,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# HOffice 11.20.0.1520+h1 bundled Qt/QPA ABI lock",
        "",
        f"- Package: `{control.get('Package', '')}`",
        f"- Version: `{control.get('Version', '')}`",
        f"- Architecture: `{control.get('Architecture', '')}`",
        f"- Qt-related ELF objects: **{len(candidates)}**",
        f"- Core/Gui/Widgets objects: **{len(core)}**",
        f"- QPA platform plugins: **{len(platforms)}**",
        f"- Platform themes: **{len(platform_themes)}**",
        f"- Input-context plugins: **{len(input_contexts)}**",
        "",
        "## Core libraries",
        "",
    ]
    lines.extend(f"- `/{path.relative_to(root).as_posix()}`" for path in core)
    lines.extend(["", "## Platform plugins", ""])
    lines.extend(f"- `/{path.relative_to(root).as_posix()}`" for path in platforms)
    lines.extend(["", "## Platform input contexts", ""])
    lines.extend(
        f"- `/{path.relative_to(root).as_posix()}`" for path in input_contexts
    )
    lines.extend([
        "",
        "The JSON lock contains SHA-256, ELF headers, SONAME/NEEDED, version",
        "requirements, selected exports, metadata sections, and diagnostic",
        "strings for every bundled Qt/QPA-related ELF object.",
        "",
    ])
    args.markdown.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
