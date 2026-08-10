#!/usr/bin/env python3
"""Add a resumable one-shot INT3 probe handler to an M3 bridge."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def c_string(value: str) -> str:
    return json.dumps(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    original = bytes.fromhex(manifest["original_bytes_hex"])
    patched = bytes.fromhex(manifest["patched_bytes_hex"])
    if len(original) < 4 or len(original) != len(patched):
        raise SystemExit("invalid INT3 manifest signature")
    if patched[0] != 0xCC or patched[1:] != original[1:]:
        raise SystemExit("manifest is not a first-byte INT3 patch")
    if "int3_probe_signal_handler(" in text:
        raise SystemExit("INT3 probe handler is already present")

    label = str(manifest["label"])
    symbol = str(manifest["symbol"]["name"])
    proof = f"HRT M5 INT3: guest {label} entered ({symbol})\n"
    signature = ", ".join(f"0x{byte:02x}u" for byte in original)

    handler = f'''
static const unsigned char g_int3_probe_original[] = {{{signature}}};
static volatile sig_atomic_t g_int3_probe_hit;

static int int3_probe_signature_matches(const unsigned char *site) {{
    if (site == NULL || site[0] != 0xccu) return 0;
    for (size_t index = 1u;
         index < sizeof(g_int3_probe_original); ++index) {{
        if (site[index] != g_int3_probe_original[index]) return 0;
    }}
    return 1;
}}

static int restore_int3_probe(unsigned char *site) {{
    uintptr_t page = (uintptr_t)site & ~(uintptr_t)(g_page_size - 1u);
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int writable = mprotect((void *)page, g_page_size,
                            PROT_READ | PROT_WRITE | PROT_EXEC);
    int saved_errno = errno;
    restore_guest_context(guest);
    if (writable != 0) {{
        errno = saved_errno;
        return -1;
    }}

    site[0] = g_int3_probe_original[0];
    __builtin___clear_cache((char *)site, (char *)site + 1);

    guest = switch_to_host_context();
    errno = 0;
    int executable = mprotect((void *)page, g_page_size,
                              PROT_READ | PROT_EXEC);
    saved_errno = errno;
    restore_guest_context(guest);
    if (executable != 0) {{
        errno = saved_errno;
        return -1;
    }}
    return 0;
}}

static void int3_probe_signal_handler(int signal_number, siginfo_t *info,
                                      void *context_pointer) {{
    ucontext_t *context = (ucontext_t *)context_pointer;
    uintptr_t after = (uintptr_t)context->uc_mcontext->__ss.__rip;
    unsigned char *site = after != 0u
        ? (unsigned char *)(after - 1u) : NULL;
    if (signal_number == SIGTRAP &&
        int3_probe_signature_matches(site) != 0 &&
        g_int3_probe_hit == 0) {{
        if (restore_int3_probe(site) == 0) {{
            static const char proof[] = {c_string(proof)};
            g_int3_probe_hit = 1;
            context->uc_mcontext->__ss.__rip = (uint64_t)(uintptr_t)site;
            raw_write_literal(proof, sizeof(proof) - 1u);
            return;
        }}
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
    trap_replacement = '''    struct sigaction trap_action = action;
    trap_action.sa_sigaction = int3_probe_signal_handler;
    if (sigaction(SIGTRAP, &trap_action, NULL) != 0) {
        fatal("M3 sigaction(SIGTRAP INT3 probe)");
    }
'''
    text = replace_once(text, trap_block, trap_replacement,
                        "SIGTRAP probe installation")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
