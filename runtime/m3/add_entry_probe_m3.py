#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

PROOF = "HRT M3: real HOffice ELF reached its original process entry point"


def replace_once(source: str, anchor: str, replacement: str, label: str) -> str:
    count = source.count(anchor)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return source.replace(anchor, replacement, 1)


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} INPUT.c OUTPUT.c", file=sys.stderr)
        return 64

    source_path = pathlib.Path(sys.argv[1])
    output_path = pathlib.Path(sys.argv[2])
    source = source_path.read_text(encoding="utf-8")

    include_anchor = '#include "hrt_m3.h"\n'
    source = replace_once(
        source,
        include_anchor,
        include_anchor + '#include "probe.h"\n',
        "M3 probe include",
    )

    signal_anchor = '''    const unsigned char *instruction =
        (const unsigned char *)(uintptr_t)rip;
    if (instruction[0] != 0x0fu || instruction[1] != 0x0bu) {
'''
    signal_replacement = f'''    const unsigned char *instruction =
        (const unsigned char *)(uintptr_t)rip;
    if (rip == g_m3_entry_probe) {{
        static const char proof[] =
            "{PROOF}\\n";
        (void)raw_bsd_syscall3(
            DARWIN_SYS_WRITE, STDOUT_FILENO,
            (uint64_t)(uintptr_t)proof, sizeof(proof) - 1u);
        raw_exit(0);
    }}
    if (instruction[0] != 0x0fu || instruction[1] != 0x0bu) {{
'''
    source = replace_once(
        source,
        signal_anchor,
        signal_replacement,
        "M3 SIGILL entry gate",
    )

    if source.count(PROOF) != 1:
        raise SystemExit("M3 proof marker was not injected exactly once")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
