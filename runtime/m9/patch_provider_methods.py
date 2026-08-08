#!/usr/bin/env python3
"""Patch the exact HWord bootstrap-provider methods with one-shot INT3 gates.

The provider/substr diagnosis resolves virtual slots 0x130 and 0x138 to exact
file-backed executable mappings.  This tool converts those runtime addresses
to guest paths and file offsets, verifies each object against the prepatch
rootfs lock, and replaces only the first byte of each selected method with
INT3.  Any missing, ambiguous, already-patched, or hash-mismatched input fails
without writing a partial manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SLOTS = (("method_130", 0x130), ("method_138", 0x138))
SIGNATURE_LENGTH = 24


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guest_path_from_host(host_path: str) -> str:
    candidates = []
    for marker in ("/opt/", "/lib/", "/lib64/", "/usr/", "/etc/"):
        position = host_path.find(marker)
        if position >= 0:
            candidates.append((position, host_path[position:]))
    if not candidates:
        raise SystemExit(f"cannot derive guest path from mapping: {host_path}")
    return min(candidates, key=lambda item: item[0])[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--diagnosis", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    diagnosis = json.loads(args.diagnosis.read_text())
    if diagnosis.get("status") != "PASS":
        raise SystemExit("provider diagnosis is not PASS")
    owners = diagnosis.get("provider_address_owners")
    if not isinstance(owners, dict):
        raise SystemExit("provider diagnosis has no address-owner table")

    prepatch_path = root / ".hrt-prepatched-v1"
    prepatch = json.loads(prepatch_path.read_text())
    locked_objects = {item["path"]: item for item in prepatch["objects"]}

    planned: list[dict[str, Any]] = []
    for key, slot in SLOTS:
        owner = owners.get(key)
        if not isinstance(owner, dict):
            raise SystemExit(f"{key}: no executable owner mapping")
        guest_path = guest_path_from_host(str(owner["host_path"]))
        image = root / guest_path.lstrip("/")
        if not image.is_file():
            raise SystemExit(f"{key}: guest object is missing: {guest_path}")
        lock = locked_objects.get(guest_path)
        if lock is None:
            raise SystemExit(f"{key}: object is absent from prepatch lock: {guest_path}")
        current_hash = sha256(image)
        if current_hash != lock["sha256_after"]:
            raise SystemExit(
                f"{key}: object hash differs from prepatch lock: "
                f"{current_hash} != {lock['sha256_after']}")
        file_offset = int(owner["object_file_offset"])
        data = image.read_bytes()
        if file_offset < 0 or file_offset + SIGNATURE_LENGTH > len(data):
            raise SystemExit(f"{key}: invalid file offset 0x{file_offset:x}")
        original = data[file_offset:file_offset + SIGNATURE_LENGTH]
        if original[0] in (0x00, 0xCC):
            raise SystemExit(
                f"{key}: unsafe first opcode 0x{original[0]:02x} at "
                f"{guest_path}+0x{file_offset:x}")
        planned.append({
            "key": key,
            "slot": slot,
            "guest_path": guest_path,
            "image": image,
            "file_offset": file_offset,
            "runtime_address_from_probe": diagnosis["provider"][key],
            "original_bytes": original,
            "sha256_before": current_hash,
        })

    # Apply only after every target has passed validation.
    records = []
    for item in planned:
        image = item["image"]
        data = bytearray(image.read_bytes())
        file_offset = item["file_offset"]
        current = bytes(data[file_offset:file_offset + SIGNATURE_LENGTH])
        if current != item["original_bytes"]:
            raise SystemExit(f"{item['key']}: object changed during validation")
        data[file_offset] = 0xCC
        image.write_bytes(data)
        patched = bytes(data[file_offset:file_offset + SIGNATURE_LENGTH])
        records.append({
            "key": item["key"],
            "slot": item["slot"],
            "guest_path": item["guest_path"],
            "file_offset": file_offset,
            "runtime_address_from_probe": item["runtime_address_from_probe"],
            "signature_length": SIGNATURE_LENGTH,
            "original_bytes_hex": item["original_bytes"].hex(),
            "patched_bytes_hex": patched.hex(),
            "sha256_before": item["sha256_before"],
            "sha256_after": sha256(image),
        })

    manifest = {
        "schema": 1,
        "kind": "HWord bootstrap provider culture override",
        "source_diagnosis": str(args.diagnosis),
        "source_workflow_run": diagnosis.get("source_workflow_run"),
        "provider_type": diagnosis["provider"].get("type_name"),
        "substring": diagnosis.get("substring"),
        "patches": records,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
