#!/usr/bin/env python3
"""Run the product closure-fill generator with nested escapes preserved.

``augment_full_product_replay.py`` emits two Python here-documents inside a
Python triple-quoted replacement.  A single ``\\n`` in the generator source is
interpreted by the outer Python parser and becomes a literal newline inside an
inner single-quoted string.  Patch only the four inner newline expressions to
contain two source backslashes, then invoke the reviewed generator unchanged.
"""
from __future__ import annotations

from pathlib import Path


def replace_exact(text: str, old: str, new: str,
                  expected: int, label: str) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{label}: expected {expected} generator anchors, found {count}"
        )
    return text.replace(old, new)


def main() -> None:
    generator = Path(__file__).with_name("augment_full_product_replay.py")
    source = generator.read_text(encoding="utf-8")
    source = replace_exact(
        source,
        r"''.join(value + '\n' for value in missing)",
        r"''.join(value + '\\n' for value in missing)",
        1,
        "missing-path newline escape",
    )
    source = replace_exact(
        source,
        r"''.join(value + '\n' for value in existing)",
        r"''.join(value + '\\n' for value in existing)",
        1,
        "existing-path newline escape",
    )
    source = replace_exact(
        source,
        r"}, indent=2) + '\n',",
        r"}, indent=2) + '\\n',",
        2,
        "integrity JSON newline escapes",
    )

    namespace = {
        "__name__": "hrt_m11_full_product_replay_v1_escaped",
        "__file__": str(generator),
    }
    exec(compile(source, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched product-fill generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
