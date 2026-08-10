#!/usr/bin/env python3
"""Add a terminal ``__cxa_throw`` INT3 probe to a string-override bridge.

The input bridge must already contain ``m9_string_override_signal_handler``.
This augmenter keeps the persistent provider-method override intact and handles
the exact ``__cxa_throw`` site first, recording the exception object, RTTI name,
destructor, return address, preserved registers, and nearby stack words.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--exit-status", type=int, default=194)
    args = parser.parse_args()
    if not 1 <= args.exit_status <= 255:
        raise SystemExit("exit status must be in 1..255")

    text = args.source.read_text(encoding="utf-8")
    if "m9_cxa_throw_signature_matches(" in text:
        raise SystemExit("M9 __cxa_throw probe is already present")
    if "m9_string_override_signal_handler(" not in text:
        raise SystemExit("input bridge does not contain the string override")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    original = bytes.fromhex(manifest["original_bytes_hex"])
    patched = bytes.fromhex(manifest["patched_bytes_hex"])
    if len(original) < 4 or len(original) != len(patched):
        raise SystemExit("invalid __cxa_throw INT3 signature")
    if patched[0] != 0xCC or patched[1:] != original[1:]:
        raise SystemExit("manifest is not a first-byte INT3 patch")
    signature = ", ".join(f"0x{byte:02x}u" for byte in original)

    function_anchor = "static void m9_string_override_signal_handler("
    declarations = f'''
static const unsigned char g_m9_cxa_throw_original[] = {{{signature}}};
static volatile sig_atomic_t g_m9_cxa_throw_hit;

static int m9_cxa_throw_signature_matches(const unsigned char *site) {{
    if (site == NULL || site[0] != 0xccu) return 0;
    for (size_t index = 1u;
         index < sizeof(g_m9_cxa_throw_original); ++index) {{
        if (site[index] != g_m9_cxa_throw_original[index]) return 0;
    }}
    return 1;
}}

'''
    if text.count(function_anchor) != 1:
        raise SystemExit("string-override handler anchor is not unique")
    position = text.index(function_anchor)
    text = text[:position] + declarations + text[position:]

    site_anchor = '''    unsigned char *site = after != 0u
        ? (unsigned char *)(after - 1u) : NULL;
'''
    cxa_block = site_anchor + f'''    if (signal_number == SIGTRAP &&
        m9_cxa_throw_signature_matches(site) != 0 &&
        g_m9_cxa_throw_hit == 0) {{
        g_m9_cxa_throw_hit = 1;
        const uint64_t exception_object = state->__rdi;
        const uint64_t typeinfo = state->__rsi;
        const uint64_t destructor = state->__rdx;
        const uint64_t type_name = typeinfo >= UINT64_C(0x10000)
            ? *((const uint64_t *)(uintptr_t)typeinfo + 1) : 0u;
        const uint64_t *stack =
            (const uint64_t *)(uintptr_t)state->__rsp;
        const uint64_t return_address = stack != NULL ? stack[0] : 0u;

        char buffer[3072];
        size_t cursor = 0u;
        cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
            "HRT M9 CXA THROW: site=");
        cursor = m9_override_append_hex(buffer, cursor, sizeof(buffer),
            (uint64_t)(uintptr_t)site);
#define M9_CXA_APPEND(name, value) do {{ \\
        cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer), \\
                                            " " name "="); \\
        cursor = m9_override_append_hex(buffer, cursor, sizeof(buffer), \\
                                        (uint64_t)(value)); \\
    }} while (0)
        M9_CXA_APPEND("return", return_address);
        M9_CXA_APPEND("rsp", state->__rsp);
        M9_CXA_APPEND("exception", exception_object);
        M9_CXA_APPEND("typeinfo", typeinfo);
        M9_CXA_APPEND("type-name-pointer", type_name);
        cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
                                             " type-name=");
        if (type_name >= UINT64_C(0x10000)) {{
            const char *name = (const char *)(uintptr_t)type_name;
            for (size_t index = 0u; index < 192u && name[index] != '\\0';
                 ++index) {{
                unsigned char byte = (unsigned char)name[index];
                cursor = m9_override_append_char(
                    buffer, cursor, sizeof(buffer),
                    (byte >= 32u && byte <= 126u) ? (char)byte : '?');
            }}
        }} else {{
            cursor = m9_override_append_literal(
                buffer, cursor, sizeof(buffer), "(null)");
        }}
        M9_CXA_APPEND("destructor", destructor);
        M9_CXA_APPEND("rax", state->__rax);
        M9_CXA_APPEND("rbx", state->__rbx);
        M9_CXA_APPEND("rbp", state->__rbp);
        M9_CXA_APPEND("r12", state->__r12);
        M9_CXA_APPEND("r13", state->__r13);
        M9_CXA_APPEND("r14", state->__r14);
        M9_CXA_APPEND("r15", state->__r15);
        for (size_t index = 0u; index < 4u; ++index) {{
            cursor = m9_override_append_literal(buffer, cursor,
                                                 sizeof(buffer), " exception");
            cursor = m9_override_append_char(buffer, cursor, sizeof(buffer),
                                             (char)('0' + index));
            cursor = m9_override_append_char(buffer, cursor, sizeof(buffer), '=');
            uint64_t word = 0u;
            if (exception_object >= UINT64_C(0x10000)) {{
                word = ((const uint64_t *)(uintptr_t)exception_object)[index];
            }}
            cursor = m9_override_append_hex(buffer, cursor, sizeof(buffer), word);
        }}
        for (size_t index = 0u; index < 10u; ++index) {{
            cursor = m9_override_append_literal(buffer, cursor,
                                                 sizeof(buffer), " stack");
            if (index >= 10u) {{
                cursor = m9_override_append_char(buffer, cursor,
                                                 sizeof(buffer), '1');
            }}
            cursor = m9_override_append_char(buffer, cursor, sizeof(buffer),
                                             (char)('0' + index % 10u));
            cursor = m9_override_append_char(buffer, cursor, sizeof(buffer), '=');
            cursor = m9_override_append_hex(
                buffer, cursor, sizeof(buffer),
                stack != NULL ? stack[index] : 0u);
        }}
#undef M9_CXA_APPEND
        cursor = m9_override_append_char(buffer, cursor, sizeof(buffer), '\\n');
        const size_t written = cursor < sizeof(buffer)
            ? cursor : sizeof(buffer);
        raw_write_literal(buffer, written);
        raw_exit({args.exit_status});
    }}
'''
    text = replace_once(text, site_anchor, cxa_block,
                        "string-override trap site")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
