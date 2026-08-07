#!/usr/bin/env python3
"""Add a terminal INT3 ABI probe for one exact guest method entry.

The selected ELF site is supplied by ``patch_elf_int3_at_offset.py``.  At the
first trap this generator records all SysV integer argument registers, the
return address, preserved registers, and the first four qwords reachable from
RDI and RSI.  That is sufficient to distinguish the two libstdc++ string-return
ABIs used by HOffice:

* ``this`` in RDI with an output ``std::string *`` in RSI; or
* hidden string-result pointer in RDI with ``this`` in RSI.

The diagnostic is terminal and therefore cannot perturb the method body.
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
    parser.add_argument("--exit-status", type=int, default=192)
    args = parser.parse_args()

    if not 1 <= args.exit_status <= 255:
        raise SystemExit("exit status must be in 1..255")
    text = args.source.read_text(encoding="utf-8")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    original = bytes.fromhex(manifest["original_bytes_hex"])
    patched = bytes.fromhex(manifest["patched_bytes_hex"])
    if len(original) < 4 or len(original) != len(patched):
        raise SystemExit("invalid INT3 manifest signature")
    if patched[0] != 0xCC or patched[1:] != original[1:]:
        raise SystemExit("manifest is not a first-byte INT3 patch")
    if "m9_method_abi_signal_handler(" in text:
        raise SystemExit("M9 method ABI probe is already present")

    label = str(manifest["label"])
    signature = ", ".join(f"0x{byte:02x}u" for byte in original)

    handler = f'''
static const unsigned char g_m9_method_abi_original[] = {{{signature}}};
static volatile sig_atomic_t g_m9_method_abi_hit;

static size_t m9_method_append_char(char *buffer, size_t cursor,
                                    size_t capacity, char value) {{
    if (cursor < capacity) buffer[cursor] = value;
    return cursor + 1u;
}}

static size_t m9_method_append_literal(char *buffer, size_t cursor,
                                       size_t capacity, const char *value) {{
    if (value == NULL) value = "(null)";
    for (size_t index = 0u; value[index] != '\\0'; ++index) {{
        cursor = m9_method_append_char(buffer, cursor, capacity, value[index]);
    }}
    return cursor;
}}

static size_t m9_method_append_hex(char *buffer, size_t cursor,
                                   size_t capacity, uint64_t value) {{
    static const char digits[] = "0123456789abcdef";
    cursor = m9_method_append_literal(buffer, cursor, capacity, "0x");
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {{
        unsigned int nibble = (unsigned int)((value >> shift) & 0x0fu);
        if (nibble != 0u || started != 0 || shift == 0) {{
            cursor = m9_method_append_char(buffer, cursor, capacity,
                                           digits[nibble]);
            started = 1;
        }}
    }}
    return cursor;
}}

static uint64_t m9_method_load_qword(uint64_t address, size_t index) {{
    if (address < UINT64_C(0x10000) ||
        address > UINT64_C(0x00007fffffffffff)) {{
        return 0u;
    }}
    return ((const uint64_t *)(uintptr_t)address)[index];
}}

static int m9_method_abi_signature_matches(const unsigned char *site) {{
    if (site == NULL || site[0] != 0xccu) return 0;
    for (size_t index = 1u;
         index < sizeof(g_m9_method_abi_original); ++index) {{
        if (site[index] != g_m9_method_abi_original[index]) return 0;
    }}
    return 1;
}}

static void m9_method_abi_signal_handler(int signal_number,
                                          siginfo_t *info,
                                          void *context_pointer) {{
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uintptr_t after = (uintptr_t)state->__rip;
    unsigned char *site = after != 0u
        ? (unsigned char *)(after - 1u) : NULL;
    if (signal_number == SIGTRAP &&
        m9_method_abi_signature_matches(site) != 0 &&
        g_m9_method_abi_hit == 0) {{
        g_m9_method_abi_hit = 1;
        const uint64_t *stack =
            (const uint64_t *)(uintptr_t)state->__rsp;
        const uint64_t return_address = stack != NULL ? stack[0] : 0u;

        char buffer[3072];
        size_t cursor = 0u;
        cursor = m9_method_append_literal(buffer, cursor, sizeof(buffer),
            "HRT M9 METHOD ABI: label=");
        cursor = m9_method_append_literal(buffer, cursor, sizeof(buffer),
            {c_string(label)});
#define M9_APPEND_REGISTER(name, value) do {{ \\
        cursor = m9_method_append_literal(buffer, cursor, sizeof(buffer), \\
                                          " " name "="); \\
        cursor = m9_method_append_hex(buffer, cursor, sizeof(buffer), \\
                                      (uint64_t)(value)); \\
    }} while (0)
        M9_APPEND_REGISTER("site", (uintptr_t)site);
        M9_APPEND_REGISTER("return", return_address);
        M9_APPEND_REGISTER("rsp", state->__rsp);
        M9_APPEND_REGISTER("rax", state->__rax);
        M9_APPEND_REGISTER("rbx", state->__rbx);
        M9_APPEND_REGISTER("rbp", state->__rbp);
        M9_APPEND_REGISTER("rdi", state->__rdi);
        M9_APPEND_REGISTER("rsi", state->__rsi);
        M9_APPEND_REGISTER("rdx", state->__rdx);
        M9_APPEND_REGISTER("rcx", state->__rcx);
        M9_APPEND_REGISTER("r8", state->__r8);
        M9_APPEND_REGISTER("r9", state->__r9);
        M9_APPEND_REGISTER("r12", state->__r12);
        M9_APPEND_REGISTER("r13", state->__r13);
        M9_APPEND_REGISTER("r14", state->__r14);
        M9_APPEND_REGISTER("r15", state->__r15);
        for (size_t index = 0u; index < 4u; ++index) {{
            cursor = m9_method_append_literal(buffer, cursor, sizeof(buffer),
                                              " rdi");
            cursor = m9_method_append_char(buffer, cursor, sizeof(buffer),
                                           (char)('0' + index));
            cursor = m9_method_append_char(buffer, cursor, sizeof(buffer), '=');
            cursor = m9_method_append_hex(
                buffer, cursor, sizeof(buffer),
                m9_method_load_qword(state->__rdi, index));
        }}
        for (size_t index = 0u; index < 4u; ++index) {{
            cursor = m9_method_append_literal(buffer, cursor, sizeof(buffer),
                                              " rsi");
            cursor = m9_method_append_char(buffer, cursor, sizeof(buffer),
                                           (char)('0' + index));
            cursor = m9_method_append_char(buffer, cursor, sizeof(buffer), '=');
            cursor = m9_method_append_hex(
                buffer, cursor, sizeof(buffer),
                m9_method_load_qword(state->__rsi, index));
        }}
        for (size_t index = 0u; index < 8u; ++index) {{
            cursor = m9_method_append_literal(buffer, cursor, sizeof(buffer),
                                              " stack");
            cursor = m9_method_append_char(buffer, cursor, sizeof(buffer),
                                           (char)('0' + index));
            cursor = m9_method_append_char(buffer, cursor, sizeof(buffer), '=');
            cursor = m9_method_append_hex(
                buffer, cursor, sizeof(buffer),
                stack != NULL ? stack[index] : 0u);
        }}
#undef M9_APPEND_REGISTER
        cursor = m9_method_append_char(buffer, cursor, sizeof(buffer), '\\n');
        const size_t written = cursor < sizeof(buffer)
            ? cursor : sizeof(buffer);
        raw_write_literal(buffer, written);
        raw_exit({args.exit_status});
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
    trap_replacement = '''    struct sigaction m9_method_trap_action = action;
    m9_method_trap_action.sa_sigaction = m9_method_abi_signal_handler;
    if (sigaction(SIGTRAP, &m9_method_trap_action, NULL) != 0) {
        fatal("M9 sigaction(SIGTRAP method ABI probe)");
    }
'''
    text = replace_once(text, trap_block, trap_replacement,
                        "SIGTRAP method-probe installation")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
