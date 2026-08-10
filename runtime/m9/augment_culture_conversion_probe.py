#!/usr/bin/env python3
"""Probe CHwordUtilityEx's wide-to-ANSI culture conversion call.

The exact caller in libHwordApp.so invokes the CHwordUtilityEx virtual slot
+0x20 immediately after Hnc::Framework::GetCulture().  ``before`` records the
actual SysV arguments at the indirect call; ``after`` records the destination
std::string and conversion return value at the next instruction.
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
    parser.add_argument("--exit-status", type=int, default=194)
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
    if "m9_culture_conversion_probe_handler(" in text:
        raise SystemExit("culture conversion probe is already present")

    signature = ", ".join(f"0x{byte:02x}u" for byte in original)
    label = c_string(str(manifest["label"]))
    mode = c_string(args.mode)

    if args.mode == "before":
        body = r'''
        const uint64_t receiver = state->__rdi;
        const uint64_t wide_pointer = state->__rsi;
        const uint64_t destination = state->__rdx;
        const uint64_t receiver_vtable = receiver != 0u
            ? *(const uint64_t *)(uintptr_t)receiver : 0u;
        const uint64_t method20 = receiver_vtable != 0u
            ? *(const uint64_t *)(uintptr_t)(receiver_vtable + 0x20u) : 0u;
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " receiver=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            receiver);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " vtable=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            receiver_vtable);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " method20=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            method20);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " wide-pointer=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            wide_pointer);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " wide=");
        cursor = m9_conversion_append_utf16(buffer, cursor, sizeof(buffer),
            (const uint16_t *)(uintptr_t)wide_pointer, 96u);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " rdx-destination=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            destination);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " outer-rbp-destination=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            state->__rbp);
'''
    else:
        body = r'''
        const uint64_t destination = state->__rbp;
        const uint64_t data = destination != 0u
            ? *(const uint64_t *)(uintptr_t)(destination + 0u) : 0u;
        const uint64_t length = destination != 0u
            ? *(const uint64_t *)(uintptr_t)(destination + 8u) : 0u;
        const uint64_t capacity_or_inline = destination != 0u
            ? *(const uint64_t *)(uintptr_t)(destination + 16u) : 0u;
        const size_t text_limit = length <= 4096u
            ? (size_t)(length < 192u ? length : 192u) : 0u;
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " destination=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            destination);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " data=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer), data);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " length=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            length);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " capacity-or-inline=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            capacity_or_inline);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " text=");
        cursor = m9_conversion_append_ascii(buffer, cursor, sizeof(buffer),
            (const char *)(uintptr_t)data, text_limit);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " return-rax=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            state->__rax);
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " receiver=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            state->__r12);
'''

    handler = f'''
static const unsigned char g_m9_conversion_original[] = {{{signature}}};
static volatile sig_atomic_t g_m9_conversion_probe_hit;

static size_t m9_conversion_append_char(char *buffer, size_t cursor,
                                        size_t capacity, char value) {{
    if (cursor < capacity) buffer[cursor] = value;
    return cursor + 1u;
}}

static size_t m9_conversion_append_literal(char *buffer, size_t cursor,
                                           size_t capacity,
                                           const char *value) {{
    if (value == NULL) value = "(null)";
    for (size_t index = 0u; value[index] != '\\0'; ++index) {{
        cursor = m9_conversion_append_char(
            buffer, cursor, capacity, value[index]);
    }}
    return cursor;
}}

static size_t m9_conversion_append_hex(char *buffer, size_t cursor,
                                       size_t capacity, uint64_t value) {{
    static const char digits[] = "0123456789abcdef";
    cursor = m9_conversion_append_literal(buffer, cursor, capacity, "0x");
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {{
        unsigned int nibble = (unsigned int)((value >> shift) & 0x0fu);
        if (nibble != 0u || started != 0 || shift == 0) {{
            cursor = m9_conversion_append_char(
                buffer, cursor, capacity, digits[nibble]);
            started = 1;
        }}
    }}
    return cursor;
}}

static size_t m9_conversion_append_ascii(char *buffer, size_t cursor,
                                         size_t capacity, const char *value,
                                         size_t maximum) {{
    if (value == NULL) {{
        return m9_conversion_append_literal(
            buffer, cursor, capacity, "(null)");
    }}
    for (size_t index = 0u; index < maximum; ++index) {{
        unsigned char byte = (unsigned char)value[index];
        if (byte == 0u) break;
        const char output = byte >= 32u && byte <= 126u ? (char)byte : '?';
        cursor = m9_conversion_append_char(
            buffer, cursor, capacity, output);
    }}
    return cursor;
}}

static size_t m9_conversion_append_utf16(char *buffer, size_t cursor,
                                         size_t capacity,
                                         const uint16_t *value,
                                         size_t maximum) {{
    if (value == NULL) {{
        return m9_conversion_append_literal(
            buffer, cursor, capacity, "(null)");
    }}
    for (size_t index = 0u; index < maximum; ++index) {{
        const uint16_t unit = value[index];
        if (unit == 0u) break;
        const char output = unit >= 32u && unit <= 126u ? (char)unit : '?';
        cursor = m9_conversion_append_char(
            buffer, cursor, capacity, output);
    }}
    return cursor;
}}

static int m9_conversion_signature_matches(const unsigned char *site) {{
    if (site == NULL || site[0] != 0xccu) return 0;
    for (size_t index = 1u;
         index < sizeof(g_m9_conversion_original); ++index) {{
        if (site[index] != g_m9_conversion_original[index]) return 0;
    }}
    return 1;
}}

static void m9_culture_conversion_probe_handler(int signal_number,
                                                 siginfo_t *info,
                                                 void *context_pointer) {{
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    const uintptr_t after = (uintptr_t)state->__rip;
    const unsigned char *site = after != 0u
        ? (const unsigned char *)(after - 1u) : NULL;
    if (signal_number == SIGTRAP &&
        m9_conversion_signature_matches(site) != 0 &&
        g_m9_conversion_probe_hit == 0) {{
        g_m9_conversion_probe_hit = 1;
        char buffer[2048];
        size_t cursor = 0u;
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            "HRT M9 CONVERSION: mode=");
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            {mode});
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " label=");
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            {label});
        cursor = m9_conversion_append_literal(buffer, cursor, sizeof(buffer),
            " site=");
        cursor = m9_conversion_append_hex(buffer, cursor, sizeof(buffer),
            (uint64_t)(uintptr_t)site);
{body}
        cursor = m9_conversion_append_char(
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
    trap_replacement = '''    struct sigaction m9_conversion_trap = action;
    m9_conversion_trap.sa_sigaction = m9_culture_conversion_probe_handler;
    if (sigaction(SIGTRAP, &m9_conversion_trap, NULL) != 0) {
        fatal("M9 sigaction(SIGTRAP conversion probe)");
    }
'''
    text = replace_once(text, trap_block, trap_replacement,
                        "SIGTRAP conversion-probe installation")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
