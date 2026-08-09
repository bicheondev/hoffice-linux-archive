#!/usr/bin/env python3
"""Stream-scan an exact Debian data archive for HWord document binaries.

Python's stdlib ``tarfile`` does not decode Zstandard archives on the runner.
This helper deliberately uses the locked system ``zstd -dc`` process and
``tarfile`` stream mode, keeping only one package member in memory at a time.
Every matching ELF is copied with a collision-safe name and recorded with its
original package path, marker hits, size and SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile


NEEDLES: dict[bytes, str] = {
    b"DocumentTabImpl": "DocumentTabImpl",
    b"HorzScrollbar1Scrolling": "HorzScrollbar1Scrolling",
    b"HwordFrameManager": "HwordFrameManager",
    b"GetLauncherDontShowAgain": "GetLauncherDontShowAgain",
    b"SelectionChanged(int)": "SelectionChanged(int)",
    b"_ZN5hanul15DocumentTabImpl": "mangled DocumentTabImpl",
    b"CreateFrame": "CreateFrame",
}


def safe_output_name(member_name: str, used: set[str]) -> str:
    base = Path(member_name).name or "unnamed"
    name = base
    if name in used:
        prefix = hashlib.sha256(member_name.encode("utf-8")).hexdigest()[:12]
        name = f"{prefix}-{base}"
    used.add(name)
    return name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    if not args.archive.is_file():
        raise SystemExit(f"archive not found: {args.archive}")
    args.output.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    process = subprocess.Popen(
        ["zstd", "-dc", "--", str(args.archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        raise SystemExit("failed to create the zstd streaming process")

    manifest: list[dict[str, object]] = []
    used_names: set[str] = set()
    scanned_files = 0
    scanned_bytes = 0
    bin_prefix = "opt/hnc/hoffice11/bin/"

    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                if not member.isfile() or member.size <= 0:
                    continue
                normalized = member.name.lower().lstrip("./")
                if not normalized.startswith(bin_prefix):
                    continue
                source = archive.extractfile(member)
                if source is None:
                    continue
                data = source.read()
                scanned_files += 1
                scanned_bytes += len(data)
                hits = [label for needle, label in NEEDLES.items()
                        if needle in data]
                if not hits:
                    continue

                output_name = safe_output_name(member.name, used_names)
                destination = args.output / output_name
                destination.write_bytes(data)
                manifest.append({
                    "member": member.name,
                    "output": str(destination),
                    "is_elf": data.startswith(b"\x7fELF"),
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "hits": hits,
                })
    finally:
        process.stdout.close()

    stderr = process.stderr.read().decode("utf-8", errors="replace")
    return_code = process.wait()
    if return_code != 0:
        raise SystemExit(
            f"zstd failed with status {return_code}: {stderr[-2000:]}"
        )

    payload = {
        "schema": 1,
        "archive": str(args.archive),
        "scanned_files": scanned_files,
        "scanned_bytes": scanned_bytes,
        "matches": manifest,
        "zstd_stderr": stderr,
    }
    args.manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not manifest:
        raise SystemExit("no HWord document implementation marker was found")


if __name__ == "__main__":
    main()
