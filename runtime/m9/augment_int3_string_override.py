#!/usr/bin/env python3
"""Replace one exact guest virtual string method at its INT3 entry.

The override writes a valid libstdc++ C++11 small-string object, skips the
original guest method by returning through the saved stack address, and leaves
the INT3 installed so every invocation is deterministic.  Only ASCII payloads
up to the 15-byte small-string capacity are accepted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ABIS = {
    "this-rdi-out-rsi",
    "sret-rdi-this-rsi",
}


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
    parser.add_argument("--abi", choices=sorted(ABIS), required=True)
    parser.add_argument("--value", required=True)
    args = parser.parse_args()

    try:
        value = args.value.encode("ascii")
    except UnicodeEncodeError as error:
        raise SystemExit("override value must be ASCII") from error
    if len(value) > 15:
        raise SystemExit("override value exceeds libstdc++ SSO capacity (15)")

    text = args.source.read_text(encoding="utf-8")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    original = bytes.fromhex(manifest["original_bytes_hex"])
    patched = bytes.fromhex(manifest["patched_bytes_hex"])
    if len(original) < 4 or len(original) != len(patched):
        raise SystemExit("invalid INT3 manifest signature")
    if patched[0] != 0xCC or patched[1:] != original[1:]:
        raise SystemExit("manifest is not a first-byte INT3 patch")
    if "m9_string_override_signal_handler(" in text:
        raise SystemExit("M9 string override is already present")

    label = str(manifest["label"])
    signature = ", ".join(f"0x{byte:02x}u" for byte in original)
    candidate_bytes = ", ".join(
        [*(f"0x{byte:02x}u" for byte in value), "0x00u"]
    )
    if args.abi == "this-rdi-out-rsi":
        this_expression = "state->__rdi"
        output_expression = "state->__rsi"
    else:
        this_expression = "state->__rsi"
        output_expression = "state->__rdi"

    handler = f'''
static const unsigned char g_m9_string_override_original[] = {{{signature}}};
static const unsigned char g_m9_string_override_value[] = {{{candidate_bytes}}};
static volatile sig_atomic_t g_m9_string_override_hits;

static size_t m9_override_append_char(char *buffer, size_t cursor,
                                      size_t capacity, char value) {{
    if (cursor < capacity) buffer[cursor] = value;
    return cursor + 1u;
}}

static size_t m9_override_append_literal(char *buffer, size_t cursor,
                                         size_t capacity,
                                         const char *value) {{
    if (value == NULL) value = "(null)";
    for (size_t index = 0u; value[index] != '\\0'; ++index) {{
        cursor = m9_override_append_char(buffer, cursor, capacity,
                                         value[index]);
    }}
    return cursor;
}}

static size_t m9_override_append_hex(char *buffer, size_t cursor,
                                     size_t capacity, uint64_t value) {{
    static const char digits[] = "0123456789abcdef";
    cursor = m9_override_append_literal(buffer, cursor, capacity, "0x");
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {{
        unsigned int nibble = (unsigned int)((value >> shift) & 0x0fu);
        if (nibble != 0u || started != 0 || shift == 0) {{
            cursor = m9_override_append_char(buffer, cursor, capacity,
                                             digits[nibble]);
            started = 1;
        }}
    }}
    return cursor;
}}

static int m9_string_override_signature_matches(
        const unsigned char *site) {{
    if (site == NULL || site[0] != 0xccu) return 0;
    for (size_t index = 1u;
         index < sizeof(g_m9_string_override_original); ++index) {{
        if (site[index] != g_m9_string_override_original[index]) return 0;
    }}
    return 1;
}}

static int m9_write_small_string(uint64_t object_address) {{
    if (object_address < UINT64_C(0x10000) ||
        object_address > UINT64_C(0x00007fffffffffff)) {{
        return -1;
    }}
    unsigned char *object = (unsigned char *)(uintptr_t)object_address;
    unsigned char *local = object + 16u;
    *(uint64_t *)(void *)(object + 0u) = (uint64_t)(uintptr_t)local;
    *(uint64_t *)(void *)(object + 8u) =
        (uint64_t)(sizeof(g_m9_string_override_value) - 1u);
    for (size_t index = 0u; index < 16u; ++index) local[index] = 0u;
    for (size_t index = 0u;
         index < sizeof(g_m9_string_override_value) - 1u; ++index) {{
        local[index] = g_m9_string_override_value[index];
    }}
    return 0;
}}

static void m9_string_override_signal_handler(int signal_number,
                                               siginfo_t *info,
                                               void *context_pointer) {{
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uintptr_t after = (uintptr_t)state->__rip;
    unsigned char *site = after != 0u
        ? (unsigned char *)(after - 1u) : NULL;
    if (signal_number == SIGTRAP &&
        m9_string_override_signature_matches(site) != 0) {{
        const uint64_t this_object = {this_expression};
        const uint64_t output_object = {output_expression};
        const uint64_t *stack =
            (const uint64_t *)(uintptr_t)state->__rsp;
        const uint64_t return_address = stack != NULL ? stack[0] : 0u;
        if (return_address == 0u ||
            m9_write_small_string(output_object) != 0) {{
            static const char failure[] =
                "HRT M9 METHOD OVERRIDE: invalid output or return address\\n";
            raw_write_literal(failure, sizeof(failure) - 1u);
            raw_exit(193);
        }}

        ++g_m9_string_override_hits;
        if (g_m9_string_override_hits <= 32) {{
            char buffer[1024];
            size_t cursor = 0u;
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), "HRT M9 METHOD OVERRIDE: label=");
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), {c_string(label)});
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), " abi=");
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), {c_string(args.abi)});
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), " value=");
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), {c_string(args.value)});
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), " hit=");
            cursor = m9_override_append_hex(buffer, cursor,
                sizeof(buffer),
                (uint64_t)(unsigned int)g_m9_string_override_hits);
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), " this=");
            cursor = m9_override_append_hex(buffer, cursor,
                sizeof(buffer), this_object);
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), " output=");
            cursor = m9_override_append_hex(buffer, cursor,
                sizeof(buffer), output_object);
            cursor = m9_override_append_literal(buffer, cursor,
                sizeof(buffer), " return=");
            cursor = m9_override_append_hex(buffer, cursor,
                sizeof(buffer), return_address);
            cursor = m9_override_append_char(buffer, cursor,
                sizeof(buffer), '\\n');
            const size_t written = cursor < sizeof(buffer)
                ? cursor : sizeof(buffer);
            raw_write_literal(buffer, written);
        }}

        state->__rax = output_object;
        state->__rsp += sizeof(uint64_t);
        state->__rip = return_address;
        return;
    }}
    crash_signal_handler(signal_number, info, context_pointer);
}}

'''

    initialize_anchor = "void initialize_syscall_bridge("
    if text.count(initialize_anchor) != 1:
        raise SystemExit("initialize bridge anchor is not unique")
    position = text.index(initialize_anchor)
    text = text[:position] + handler + text[position:]

    trap_block = '''    if (sigaction(SIGTRAP, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGTRAP)");
    }
'''
    trap_replacement = '''    struct sigaction m9_override_trap_action = action;
    m9_override_trap_action.sa_sigaction =
        m9_string_override_signal_handler;
    if (sigaction(SIGTRAP, &m9_override_trap_action, NULL) != 0) {
        fatal("M9 sigaction(SIGTRAP string override)");
    }
'''
    text = replace_once(text, trap_block, trap_replacement,
                        "SIGTRAP override installation")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
