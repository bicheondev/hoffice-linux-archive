#!/usr/bin/env python3
"""Run the M11 multi-window transform with a resilient attach-block matcher.

The generated Objective-C source contains the reviewed input-attach block, but
its C string newline has passed through several Python generators and therefore
may contain one or more literal backslashes.  The v1 transform intentionally
used an exact block anchor and rejected that representational difference.

Patch only that one generator section in memory.  Every other v1 source anchor
and invariant remains unchanged.  The replacement still requires exactly one
``hrt_m8_input_attach`` block and fails closed otherwise.  ``re.sub`` is given
a callable replacement so it cannot reinterpret ``\\n`` in the Objective-C
source as a physical newline inside the generated string literal.
"""
from __future__ import annotations

from pathlib import Path


def main() -> None:
    generator = Path(__file__).with_name("augment_appkit_multiwindow.py")
    source = generator.read_text(encoding="utf-8")

    start_token = "    attach_anchor = '''"
    end_token = (
        '    text = replace_once(text, attach_anchor, attach_replacement,\n'
        '                        "primary-only input attachment")\n'
    )
    start = source.find(start_token)
    if start < 0:
        raise SystemExit("v1 attach-transform start not found")
    end = source.find(end_token, start)
    if end < 0:
        raise SystemExit("v1 attach-transform end not found")
    end += len(end_token)

    replacement = r"""    attach_pattern = re.compile(
        r'    const int input_result = hrt_m8_input_attach\(\(__bridge void \*\)g_window\);\n'
        r'    fprintf\(stderr, "HRT M8 APPKIT: attach result=%d[^\n]*\n'
        r'    fflush\(stderr\);\n'
    )
    attach_replacement = r'''    int input_result = 0;
    const BOOL claim_input = g_m11_input_window == nil;
    if (claim_input) {
        input_result = hrt_m8_input_attach((__bridge void *)g_window);
        if (input_result == 0)
            g_m11_input_window = g_window;
    }
    fprintf(stderr,
            "HRT M8 APPKIT: attach result=%d claimed=%d window=%ld input-window=%ld\n",
            input_result, claim_input ? 1 : 0,
            (long)g_window.windowNumber,
            g_m11_input_window != nil
                ? (long)g_m11_input_window.windowNumber : 0L);
    fflush(stderr);
'''
    text, attach_count = attach_pattern.subn(
        lambda _match: attach_replacement, text, count=1)
    if attach_count != 1:
        raise SystemExit(
            f"primary-only input attachment: expected one regex anchor, "
            f"found {attach_count}")
"""
    patched = source[:start] + replacement + source[end:]
    if "import re\n" not in patched:
        patched = patched.replace(
            "from pathlib import Path\n",
            "from pathlib import Path\nimport re\n",
            1,
        )

    namespace = {
        "__name__": "hrt_m11_appkit_multiwindow_v1_attach_escaped",
        "__file__": str(generator),
    }
    exec(compile(patched, str(generator), "exec"), namespace)
    entry = namespace.get("main")
    if entry is None:
        raise SystemExit("patched multi-window generator has no main entry")
    entry()


if __name__ == "__main__":
    main()
