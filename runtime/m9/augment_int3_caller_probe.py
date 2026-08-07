#!/usr/bin/env python3
"""Add a terminal INT3 caller probe to a mature M3/M6 bridge.

Unlike the resumable M5 probe, this diagnostic stops at the first entry into
an exact function, records the return address at ``[RSP]`` together with the
format argument and nearby stack words, and exits with a dedicated status.
The companion executable-mmap trace attributes the return address to an exact
guest ELF object and file offset after the run.
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
    parser.add_argument("--exit-status", type=int, default=191)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    original = bytes.fromhex(manifest["original_bytes_hex"])
    patched = bytes.fromhex(manifest["patched_bytes_hex"])
    if len(original) < 4 or len(original) != len(patched):
        raise SystemExit("invalid INT3 manifest signature")
    if patched[0] != 0xCC or patched[1:] != original[1:]:
        raise SystemExit("manifest is not a first-byte INT3 patch")
    if "m9_int3_caller_signal_handler(" in text:
        raise SystemExit("M9 caller probe is already present")
    if not (1 <= args.exit_status <= 255):
        raise SystemExit("exit status must be in 1..255")

    label = str(manifest["label"])
    symbol = str(manifest["symbol"]["name"])
    signature = ", ".join(f"0x{byte:02x}u" for byte in original)

    handler = f'''
static const unsigned char g_m9_int3_original[] = {{{signature}}};
static volatile sig_atomic_t g_m9_int3_caller_hit;

static size_t m9_probe_append_char(char *buffer, size_t cursor,
                                   size_t capacity, char value) {{
    if (cursor < capacity) buffer[cursor] = value;
    return cursor + 1u;
}}

static size_t m9_probe_append_literal(char *buffer, size_t cursor,
                                      size_t capacity, const char *value) {{
    if (value == NULL) value = "(null)";
    for (size_t index = 0u; value[index] != '\\0'; ++index) {{
        cursor = m9_probe_append_char(buffer, cursor, capacity, value[index]);
    }}
    return cursor;
}}

static size_t m9_probe_append_hex(char *buffer, size_t cursor,
                                  size_t capacity, uint64_t value) {{
    static const char digits[] = "0123456789abcdef";
    cursor = m9_probe_append_literal(buffer, cursor, capacity, "0x");
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {{
        unsigned int nibble = (unsigned int)((value >> shift) & 0x0fu);
        if (nibble != 0u || started != 0 || shift == 0) {{
            cursor = m9_probe_append_char(buffer, cursor, capacity,
                                          digits[nibble]);
            started = 1;
        }}
    }}
    return cursor;
}}

static size_t m9_probe_append_guest_string(char *buffer, size_t cursor,
                                           size_t capacity,
                                           const char *value,
                                           size_t maximum) {{
    if (value == NULL) {{
        return m9_probe_append_literal(buffer, cursor, capacity, "(null)");
    }}
    for (size_t index = 0u; index < maximum; ++index) {{
        unsigned char byte = (unsigned char)value[index];
        if (byte == 0u) break;
        char output = (byte >= 32u && byte <= 126u) ? (char)byte : '?';
        cursor = m9_probe_append_char(buffer, cursor, capacity, output);
    }}
    return cursor;
}}

static int m9_int3_signature_matches(const unsigned char *site) {{
    if (site == NULL || site[0] != 0xccu) return 0;
    for (size_t index = 1u; index < sizeof(g_m9_int3_original); ++index) {{
        if (site[index] != g_m9_int3_original[index]) return 0;
    }}
    return 1;
}}

static void m9_int3_caller_signal_handler(int signal_number,
                                           siginfo_t *info,
                                           void *context_pointer) {{
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uintptr_t after = (uintptr_t)state->__rip;
    unsigned char *site = after != 0u
        ? (unsigned char *)(after - 1u) : NULL;
    if (signal_number == SIGTRAP &&
        m9_int3_signature_matches(site) != 0 &&
        g_m9_int3_caller_hit == 0) {{
        g_m9_int3_caller_hit = 1;
        const uint64_t *stack = (const uint64_t *)(uintptr_t)state->__rsp;
        uint64_t return_address = stack != NULL ? stack[0] : 0u;

        char buffer[1536];
        size_t cursor = 0u;
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            "HRT M9 THROW INT3: label=");
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            {c_string(label)});
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            " symbol=");
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            {c_string(symbol)});
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            " site=");
        cursor = m9_probe_append_hex(buffer, cursor, sizeof(buffer),
            (uint64_t)(uintptr_t)site);
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            " return=");
        cursor = m9_probe_append_hex(buffer, cursor, sizeof(buffer),
            return_address);
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            " rsp=");
        cursor = m9_probe_append_hex(buffer, cursor, sizeof(buffer),
            state->__rsp);
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            " rdi=");
        cursor = m9_probe_append_hex(buffer, cursor, sizeof(buffer),
            state->__rdi);
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            " rsi=");
        cursor = m9_probe_append_hex(buffer, cursor, sizeof(buffer),
            state->__rsi);
        cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
            " format=");
        cursor = m9_probe_append_guest_string(buffer, cursor, sizeof(buffer),
            (const char *)(uintptr_t)state->__rdi, 192u);
        for (size_t index = 0u; index < 8u; ++index) {{
            cursor = m9_probe_append_literal(buffer, cursor, sizeof(buffer),
                " stack");
            cursor = m9_probe_append_char(buffer, cursor, sizeof(buffer),
                (char)('0' + index));
            cursor = m9_probe_append_char(buffer, cursor, sizeof(buffer), '=');
            cursor = m9_probe_append_hex(buffer, cursor, sizeof(buffer),
                stack != NULL ? stack[index] : 0u);
        }}
        cursor = m9_probe_append_char(buffer, cursor, sizeof(buffer), '\\n');
        size_t written = cursor < sizeof(buffer) ? cursor : sizeof(buffer);
        raw_write_literal(buffer, written);
        raw_exit({args.exit_status});
    }}
    crash_signal_handler(signal_number, info, context_pointer);
}}

'''

    initialize_anchor = "void initialize_syscall_bridge("
    count = text.count(initialize_anchor)
    if count != 1:
        raise SystemExit(
            f"initialize bridge: expected one anchor, found {count}")
    position = text.index(initialize_anchor)
    text = text[:position] + handler + text[position:]

    trap_block = '''    if (sigaction(SIGTRAP, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGTRAP)");
    }
'''
    trap_replacement = '''    struct sigaction m9_trap_action = action;
    m9_trap_action.sa_sigaction = m9_int3_caller_signal_handler;
    if (sigaction(SIGTRAP, &m9_trap_action, NULL) != 0) {
        fatal("M9 sigaction(SIGTRAP caller probe)");
    }
'''
    text = replace_once(text, trap_block, trap_replacement,
                        "SIGTRAP caller-probe installation")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
