#!/usr/bin/env python3
"""Inject a terminal SIGTRAP probe around CHwordUtilityEx culture lookup.

Two exact-address probes are used by the M9 workflow:

* ``before`` stops on the indirect call at libHwordApp.so:0x411121 and records
  the actual framework object, vtable, RTTI, GetSite slot and culture slot.
* ``after`` stops at 0x411127 and records the CHncStringW object returned by the
  culture call, including a bounded UTF-16 preview.

Both modes preserve the mature runtime's normal crash handler for every other
SIGTRAP and exit only after the exact signature-locked site is observed.
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


def c_string(value: str) -> str:
    return json.dumps(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("before", "after"), required=True)
    parser.add_argument("--exit-status", type=int, default=192)
    args = parser.parse_args()
    if not (1 <= args.exit_status <= 255):
        raise SystemExit("exit status must be in 1..255")

    text = args.source.read_text(encoding="utf-8")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    original = bytes.fromhex(manifest["original_bytes_hex"])
    patched = bytes.fromhex(manifest["patched_bytes_hex"])
    if len(original) < 4 or len(original) != len(patched):
        raise SystemExit("invalid exact-address INT3 manifest")
    if patched[0] != 0xCC or patched[1:] != original[1:]:
        raise SystemExit("manifest is not a first-byte INT3 patch")
    if "m9_framework_call_probe_handler(" in text:
        raise SystemExit("framework-call probe is already present")

    signature = ", ".join(f"0x{byte:02x}u" for byte in original)
    label = c_string(str(manifest["label"]))
    mode = c_string(args.mode)

    if args.mode == "before":
        body = r'''
        const uint64_t output_object = state->__rdi;
        const uint64_t framework_object = state->__rsi;
        const uint64_t framework_vtable = state->__rdx;
        const uint64_t offset_to_top = framework_vtable != 0u
            ? *((const uint64_t *)(uintptr_t)framework_vtable - 2) : 0u;
        const uint64_t typeinfo = framework_vtable != 0u
            ? *((const uint64_t *)(uintptr_t)framework_vtable - 1) : 0u;
        const uint64_t type_name_pointer = typeinfo != 0u
            ? *((const uint64_t *)(uintptr_t)typeinfo + 1) : 0u;
        const uint64_t method40 = framework_vtable != 0u
            ? *(const uint64_t *)(uintptr_t)(framework_vtable + 0x40u) : 0u;
        const uint64_t method128 = framework_vtable != 0u
            ? *(const uint64_t *)(uintptr_t)(framework_vtable + 0x128u) : 0u;

        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " framework=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            framework_object);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " vtable=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            framework_vtable);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " offset-to-top=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            offset_to_top);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " typeinfo=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            typeinfo);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " type-name-pointer=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            type_name_pointer);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " type-name=");
        cursor = m9_framework_append_ascii(buffer, cursor, sizeof(buffer),
            (const char *)(uintptr_t)type_name_pointer, 160u);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " method40=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            method40);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " method128=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            method128);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " output-object=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            output_object);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " provider=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            state->__r12);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " destination-string=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            state->__rbp);
'''
    else:
        body = r'''
        const uint64_t output_object = state->__rbx;
        const uint64_t qword0 = output_object != 0u
            ? *(const uint64_t *)(uintptr_t)(output_object + 0u) : 0u;
        const uint64_t qword1 = output_object != 0u
            ? *(const uint64_t *)(uintptr_t)(output_object + 8u) : 0u;
        const uint64_t qword2 = output_object != 0u
            ? *(const uint64_t *)(uintptr_t)(output_object + 16u) : 0u;
        const uint64_t qword3 = output_object != 0u
            ? *(const uint64_t *)(uintptr_t)(output_object + 24u) : 0u;

        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " output-object=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            output_object);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " qword0=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer), qword0);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " qword1=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer), qword1);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " qword2=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer), qword2);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " qword3=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer), qword3);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " wide-pointer=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer), qword0);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " wide=");
        cursor = m9_framework_append_utf16(buffer, cursor, sizeof(buffer),
            (const uint16_t *)(uintptr_t)qword0, 96u);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " return-rax=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            state->__rax);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " provider=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            state->__r12);
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " destination-string=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            state->__rbp);
'''

    handler = f'''
static const unsigned char g_m9_framework_original[] = {{{signature}}};
static volatile sig_atomic_t g_m9_framework_probe_hit;

static size_t m9_framework_append_char(char *buffer, size_t cursor,
                                       size_t capacity, char value) {{
    if (cursor < capacity) buffer[cursor] = value;
    return cursor + 1u;
}}

static size_t m9_framework_append_literal(char *buffer, size_t cursor,
                                          size_t capacity,
                                          const char *value) {{
    if (value == NULL) value = "(null)";
    for (size_t index = 0u; value[index] != '\\0'; ++index) {{
        cursor = m9_framework_append_char(
            buffer, cursor, capacity, value[index]);
    }}
    return cursor;
}}

static size_t m9_framework_append_hex(char *buffer, size_t cursor,
                                      size_t capacity, uint64_t value) {{
    static const char digits[] = "0123456789abcdef";
    cursor = m9_framework_append_literal(buffer, cursor, capacity, "0x");
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {{
        unsigned int nibble = (unsigned int)((value >> shift) & 0x0fu);
        if (nibble != 0u || started != 0 || shift == 0) {{
            cursor = m9_framework_append_char(
                buffer, cursor, capacity, digits[nibble]);
            started = 1;
        }}
    }}
    return cursor;
}}

static size_t m9_framework_append_ascii(char *buffer, size_t cursor,
                                        size_t capacity, const char *value,
                                        size_t maximum) {{
    if (value == NULL) {{
        return m9_framework_append_literal(
            buffer, cursor, capacity, "(null)");
    }}
    for (size_t index = 0u; index < maximum; ++index) {{
        unsigned char byte = (unsigned char)value[index];
        if (byte == 0u) break;
        const char output = byte >= 32u && byte <= 126u ? (char)byte : '?';
        cursor = m9_framework_append_char(
            buffer, cursor, capacity, output);
    }}
    return cursor;
}}

static size_t m9_framework_append_utf16(char *buffer, size_t cursor,
                                        size_t capacity,
                                        const uint16_t *value,
                                        size_t maximum) {{
    if (value == NULL) {{
        return m9_framework_append_literal(
            buffer, cursor, capacity, "(null)");
    }}
    for (size_t index = 0u; index < maximum; ++index) {{
        uint16_t unit = value[index];
        if (unit == 0u) break;
        char output = unit >= 32u && unit <= 126u ? (char)unit : '?';
        cursor = m9_framework_append_char(
            buffer, cursor, capacity, output);
    }}
    return cursor;
}}

static int m9_framework_signature_matches(const unsigned char *site) {{
    if (site == NULL || site[0] != 0xccu) return 0;
    for (size_t index = 1u;
         index < sizeof(g_m9_framework_original); ++index) {{
        if (site[index] != g_m9_framework_original[index]) return 0;
    }}
    return 1;
}}

static void m9_framework_call_probe_handler(int signal_number,
                                             siginfo_t *info,
                                             void *context_pointer) {{
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    const uintptr_t after = (uintptr_t)state->__rip;
    const unsigned char *site = after != 0u
        ? (const unsigned char *)(after - 1u) : NULL;
    if (signal_number == SIGTRAP &&
        m9_framework_signature_matches(site) != 0 &&
        g_m9_framework_probe_hit == 0) {{
        g_m9_framework_probe_hit = 1;
        char buffer[3072];
        size_t cursor = 0u;
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            "HRT M9 FRAMEWORK: mode=");
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            {mode});
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " label=");
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            {label});
        cursor = m9_framework_append_literal(buffer, cursor, sizeof(buffer),
            " site=");
        cursor = m9_framework_append_hex(buffer, cursor, sizeof(buffer),
            (uint64_t)(uintptr_t)site);
{body}
        cursor = m9_framework_append_char(
            buffer, cursor, sizeof(buffer), '\\n');
        const size_t written = cursor < sizeof(buffer)
            ? cursor : sizeof(buffer);
        raw_write_literal(buffer, written);
        raw_exit({args.exit_status});
    }}
    crash_signal_handler(signal_number, info, context_pointer);
}}

'''

    initialize_anchor = "void initialize_syscall_bridge("
    count = text.count(initialize_anchor)
    if count != 1:
        raise SystemExit(f"initialize bridge: expected one anchor, found {count}")
    position = text.index(initialize_anchor)
    text = text[:position] + handler + text[position:]

    trap_block = '''    if (sigaction(SIGTRAP, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGTRAP)");
    }
'''
    trap_replacement = '''    struct sigaction m9_framework_trap = action;
    m9_framework_trap.sa_sigaction = m9_framework_call_probe_handler;
    if (sigaction(SIGTRAP, &m9_framework_trap, NULL) != 0) {
        fatal("M9 sigaction(SIGTRAP framework probe)");
    }
'''
    text = replace_once(text, trap_block, trap_replacement,
                        "SIGTRAP framework-probe installation")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
