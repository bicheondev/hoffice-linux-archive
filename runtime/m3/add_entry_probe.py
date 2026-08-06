#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} INPUT.c OUTPUT.c", file=sys.stderr)
        return 64
    source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    include_anchor = '#include "hrt_m2.h"\n'
    if source.count(include_anchor) != 1:
        raise SystemExit("could not locate hrt_m2 include")
    source = source.replace(
        include_anchor,
        include_anchor + '#include "runtime/m3/probe.h"\n',
        1,
    )
    anchor = '''    const unsigned char *instruction = (const unsigned char *)(uintptr_t)rip;
    if (instruction[0] != 0x0f || instruction[1] != 0x0b) {
'''
    replacement = '''    const unsigned char *instruction = (const unsigned char *)(uintptr_t)rip;
    if (rip == g_m3_entry_probe) {
        static const char proof[] =
            "HRT M3: real HOffice ELF reached its original process entry point\\n";
        (void)write(STDOUT_FILENO, proof, sizeof(proof) - 1u);
        _exit(0);
    }
    if (instruction[0] != 0x0f || instruction[1] != 0x0b) {
'''
    if source.count(anchor) != 1:
        raise SystemExit("could not locate SIGILL instruction check")
    source = source.replace(anchor, replacement, 1)
    output = pathlib.Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
