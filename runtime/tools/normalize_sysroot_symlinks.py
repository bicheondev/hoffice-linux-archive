#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    rewritten: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    escaped: list[dict[str, str]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_symlink():
            continue
        target = os.readlink(path)
        relative_link = "/" + path.relative_to(root).as_posix()

        if os.path.isabs(target):
            virtual_target = root / target.lstrip("/")
            if not virtual_target.exists() and not virtual_target.is_symlink():
                unresolved.append({"link": relative_link, "target": target})
                continue
            rewritten_target = os.path.relpath(virtual_target, path.parent)
            path.unlink()
            path.symlink_to(rewritten_target)
            rewritten.append({
                "link": relative_link,
                "old_target": target,
                "new_target": rewritten_target,
            })
            continue

        lexical_target = Path(os.path.normpath(path.parent / target))
        if not within(root, lexical_target):
            escaped.append({"link": relative_link, "target": target})

    report = {
        "schema": 1,
        "root": str(root),
        "rewritten_absolute_links": rewritten,
        "unresolved_absolute_links": unresolved,
        "escaping_relative_links": escaped,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"rewritten absolute links: {len(rewritten)}")
    print(f"unresolved absolute links: {len(unresolved)}")
    print(f"escaping relative links: {len(escaped)}")
    if escaped:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
