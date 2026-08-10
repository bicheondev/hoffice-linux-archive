#!/usr/bin/env python3
"""Inject a diagnostic HWord provider-culture override into the mature bridge.

Two exact provider virtual methods are INT3-patched by
``patch_provider_methods.py``.  At either method entry this bridge identifies
the C++ ABI shape from the provider vtable itself, writes a valid libstdc++
C++11 SSO string into the hidden/output object, and simulates a normal return.
No HWord, Qt, or libstdc++ symbol is replaced globally.

The default values model the Linux culture/encoding pair HWord expects before
its ``substr(3)`` bootstrap operation:

* slot 0x130 -> ``ko_KR``
* slot 0x138 -> ``UTF-8``

This remains an explicitly diagnostic compatibility shim.  It fails closed on
an unknown ABI shape, signature mismatch, oversized value, or unrelated
SIGTRAP.
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


def c_bytes(value: bytes) -> str:
    return ", ".join(f"0x{byte:02x}u" for byte in value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--value-130", default="ko_KR")
    parser.add_argument("--value-138", default="UTF-8")
    args = parser.parse_args()

    values = {"method_130": args.value_130, "method_138": args.value_138}
    for key, value in values.items():
        encoded = value.encode("utf-8")
        if not encoded or len(encoded) > 15 or b"\0" in encoded:
            raise SystemExit(f"{key}: override must be 1..15 NUL-free UTF-8 bytes")

    manifest = json.loads(args.manifest.read_text())
    patches = manifest.get("patches")
    if not isinstance(patches, list) or len(patches) != 2:
        raise SystemExit("provider patch manifest must contain exactly two methods")
    by_key = {item["key"]: item for item in patches}
    if set(by_key) != {"method_130", "method_138"}:
        raise SystemExit(f"unexpected provider patch keys: {set(by_key)}")

    text = args.source.read_text(encoding="utf-8")
    if "HRT M9 PROVIDER OVERRIDE:" in text:
        raise SystemExit("provider culture override is already present")

    records = []
    for key in ("method_130", "method_138"):
        item = by_key[key]
        original = bytes.fromhex(item["original_bytes_hex"])
        patched = bytes.fromhex(item["patched_bytes_hex"])
        if len(original) < 8 or len(original) != len(patched):
            raise SystemExit(f"{key}: invalid method signature")
        if patched[0] != 0xCC or patched[1:] != original[1:]:
            raise SystemExit(f"{key}: manifest is not a first-byte INT3 patch")
        if int(item["slot"]) not in (0x130, 0x138):
            raise SystemExit(f"{key}: unexpected vtable slot")
        records.append((key, int(item["slot"]), original, values[key]))

    declarations = []
    descriptors = []
    for index, (key, slot, original, value) in enumerate(records):
        declarations.append(
            f"static const unsigned char g_m9_provider_signature_{index}[] = "
            f"{{{c_bytes(original)}}};\n"
            f"static const char g_m9_provider_value_{index}[] = "
            f"{c_string(value)};\n")
        descriptors.append(
            "    {"
            f"UINT64_C(0x{slot:x}), g_m9_provider_signature_{index}, "
            f"sizeof(g_m9_provider_signature_{index}), "
            f"g_m9_provider_value_{index}, "
            f"sizeof(g_m9_provider_value_{index}) - 1u, {c_string(key)}"
            "},\n")

    injected = "".join(declarations) + r'''
typedef struct {
    uint64_t slot;
    const unsigned char *signature;
    size_t signature_length;
    const char *value;
    size_t value_length;
    const char *key;
} M9ProviderOverride;

static const M9ProviderOverride g_m9_provider_overrides[] = {
''' + "".join(descriptors) + r'''};

static volatile sig_atomic_t g_m9_provider_override_count;

static int m9_provider_signature_matches(
        const unsigned char *site, const M9ProviderOverride *override) {
    if (site == NULL || override == NULL || site[0] != 0xccu ||
        override->signature_length < 2u) {
        return 0;
    }
    for (size_t index = 1u; index < override->signature_length; ++index) {
        if (site[index] != override->signature[index]) return 0;
    }
    return 1;
}

static int m9_is_provider_for_slot(uint64_t candidate,
                                   uint64_t slot,
                                   uintptr_t site) {
    if (candidate < UINT64_C(0x10000) || (candidate & 7u) != 0u) return 0;
    const uint64_t vtable = *(const uint64_t *)(uintptr_t)candidate;
    if (vtable < UINT64_C(0x10000) || (vtable & 7u) != 0u) return 0;
    const uint64_t method =
        *(const uint64_t *)(uintptr_t)(vtable + slot);
    return method == (uint64_t)site;
}

static int m9_write_guest_sso_string(uint64_t output,
                                     const char *value,
                                     size_t length) {
    if (output < UINT64_C(0x10000) || (output & 7u) != 0u ||
        value == NULL || length == 0u || length > 15u) {
        return -1;
    }
    unsigned char *object = (unsigned char *)(uintptr_t)output;
    unsigned char *local = object + 16u;
    memset(object, 0, 32u);
    *(uint64_t *)(void *)(object + 0u) = (uint64_t)(uintptr_t)local;
    *(uint64_t *)(void *)(object + 8u) = (uint64_t)length;
    memcpy(local, value, length);
    local[length] = '\0';
    return 0;
}

static size_t m9_override_append_literal(char *buffer, size_t cursor,
                                         size_t capacity,
                                         const char *value) {
    if (value == NULL) value = "(null)";
    for (size_t index = 0u; value[index] != '\0'; ++index) {
        if (cursor < capacity) buffer[cursor] = value[index];
        ++cursor;
    }
    return cursor;
}

static size_t m9_override_append_hex(char *buffer, size_t cursor,
                                     size_t capacity, uint64_t value) {
    static const char digits[] = "0123456789abcdef";
    cursor = m9_override_append_literal(buffer, cursor, capacity, "0x");
    int started = 0;
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned int nibble = (unsigned int)((value >> shift) & 0x0fu);
        if (nibble != 0u || started != 0 || shift == 0) {
            if (cursor < capacity) buffer[cursor] = digits[nibble];
            ++cursor;
            started = 1;
        }
    }
    return cursor;
}

static void m9_trace_provider_override(const M9ProviderOverride *override,
                                       uint64_t provider,
                                       uint64_t output,
                                       const char *abi) {
    char buffer[512];
    size_t cursor = 0u;
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
        "HRT M9 PROVIDER OVERRIDE: key=");
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
        override->key);
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
        " slot=");
    cursor = m9_override_append_hex(buffer, cursor, sizeof(buffer),
        override->slot);
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
        " value=");
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
        override->value);
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
        " abi=");
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer), abi);
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
        " provider=");
    cursor = m9_override_append_hex(buffer, cursor, sizeof(buffer), provider);
    cursor = m9_override_append_literal(buffer, cursor, sizeof(buffer),
        " output=");
    cursor = m9_override_append_hex(buffer, cursor, sizeof(buffer), output);
    if (cursor < sizeof(buffer)) buffer[cursor] = '\n';
    ++cursor;
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static void m9_provider_override_signal_handler(int signal_number,
                                                 siginfo_t *info,
                                                 void *context_pointer) {
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    const uintptr_t after = (uintptr_t)state->__rip;
    unsigned char *site = after != 0u
        ? (unsigned char *)(after - 1u) : NULL;

    if (signal_number == SIGTRAP && site != NULL) {
        for (size_t index = 0u;
             index < sizeof(g_m9_provider_overrides) /
                     sizeof(g_m9_provider_overrides[0]); ++index) {
            const M9ProviderOverride *override =
                &g_m9_provider_overrides[index];
            if (!m9_provider_signature_matches(site, override)) continue;

            uint64_t provider = 0u;
            uint64_t output = 0u;
            const char *abi = NULL;
            if (m9_is_provider_for_slot(state->__rdi, override->slot,
                                        (uintptr_t)site)) {
                provider = state->__rdi;
                output = state->__rsi;
                abi = "this-output";
            } else if (m9_is_provider_for_slot(state->__rsi, override->slot,
                                               (uintptr_t)site)) {
                provider = state->__rsi;
                output = state->__rdi;
                abi = "sret-this";
            } else {
                static const char message[] =
                    "HRT M9 PROVIDER OVERRIDE: unknown C++ ABI shape\n";
                raw_write_literal(message, sizeof(message) - 1u);
                raw_exit(193);
            }

            if (m9_write_guest_sso_string(output, override->value,
                                          override->value_length) != 0) {
                static const char message[] =
                    "HRT M9 PROVIDER OVERRIDE: invalid output string object\n";
                raw_write_literal(message, sizeof(message) - 1u);
                raw_exit(194);
            }
            const uint64_t *stack =
                (const uint64_t *)(uintptr_t)state->__rsp;
            if (stack == NULL || stack[0] < UINT64_C(0x10000)) {
                static const char message[] =
                    "HRT M9 PROVIDER OVERRIDE: invalid return address\n";
                raw_write_literal(message, sizeof(message) - 1u);
                raw_exit(195);
            }
            m9_trace_provider_override(override, provider, output, abi);
            ++g_m9_provider_override_count;
            state->__rax = output;
            state->__rip = stack[0];
            state->__rsp += sizeof(uint64_t);
            return;
        }
    }
    crash_signal_handler(signal_number, info, context_pointer);
}

'''

    initialize_anchor = "void initialize_syscall_bridge("
    count = text.count(initialize_anchor)
    if count != 1:
        raise SystemExit(
            f"initialize bridge: expected one anchor, found {count}")
    position = text.index(initialize_anchor)
    text = text[:position] + injected + text[position:]

    trap_anchor = '''    if (sigaction(SIGTRAP, &action, NULL) != 0) {
        fatal("M3 sigaction(SIGTRAP)");
    }
'''
    trap_replacement = '''    struct sigaction m9_provider_action = action;
    m9_provider_action.sa_sigaction = m9_provider_override_signal_handler;
    if (sigaction(SIGTRAP, &m9_provider_action, NULL) != 0) {
        fatal("M9 sigaction(SIGTRAP provider override)");
    }
'''
    text = replace_once(text, trap_anchor, trap_replacement,
                        "provider SIGTRAP installation")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
