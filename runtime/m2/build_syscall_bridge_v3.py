#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} INPUT.c OUTPUT.c", file=sys.stderr)
        return 64
    source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")

    source = replace_once(
        source,
        '#include <unistd.h>\n',
        '#include <unistd.h>\n\nextern void hrt_set_fs_trampoline(void);\n',
        'trampoline declaration',
    )
    source = replace_once(
        source,
        'static uintptr_t g_brk_limit;\n',
        'static uintptr_t g_brk_limit;\n'
        'static uint64_t g_host_fs_base;\n'
        'static uint64_t g_guest_fs_base;\n',
        'FS globals',
    )
    source = replace_once(
        source,
        '''static long handle_arch_prctl(uint64_t code, uint64_t address) {
    if (code == LINUX_ARCH_SET_FS) {
        write_fs_base(address);
        return 0;
    }
    if (code == LINUX_ARCH_GET_FS) {
        if (address == 0u) return -14;
        *(uint64_t *)(uintptr_t)address = read_fs_base();
        return 0;
    }
    return -22;
}
''',
        '''static long handle_arch_prctl(uint64_t code, uint64_t address) {
    if (code == LINUX_ARCH_GET_FS) {
        if (address == 0u) return -14;
        *(uint64_t *)(uintptr_t)address = g_guest_fs_base;
        return 0;
    }
    return -22;
}
''',
        'arch_prctl helper',
    )
    source = replace_once(
        source,
        '''    if (g_in_handler) _exit(125);
    g_in_handler = 1;

#if defined(__x86_64__)
''',
        '''    uint64_t interrupted_fs = read_fs_base();
    write_fs_base(g_host_fs_base);
    if (g_in_handler) _exit(125);
    g_in_handler = 1;

#if defined(__x86_64__)
''',
        'signal entry FS swap',
    )
    source = replace_once(
        source,
        '''        case LINUX_SYS_ARCH_PRCTL:
            result = handle_arch_prctl(state->__rdi, state->__rsi);
            break;
''',
        '''        case LINUX_SYS_ARCH_PRCTL:
            if (state->__rdi == LINUX_ARCH_SET_FS) {
                uint64_t requested_fs = state->__rsi;
                g_guest_fs_base = requested_fs;
                state->__rdi = requested_fs;
                state->__rax = 0;
                state->__rcx = rip + 2u;
                state->__r11 = rip + 2u;
                state->__rip = (uint64_t)(uintptr_t)&hrt_set_fs_trampoline;
                g_in_handler = 0;
                write_fs_base(interrupted_fs);
                return;
            }
            result = handle_arch_prctl(state->__rdi, state->__rsi);
            break;
''',
        'ARCH_SET_FS trampoline dispatch',
    )
    source = replace_once(
        source,
        '''    complete_syscall(state, rip, result);
#else
''',
        '''    write_fs_base(g_guest_fs_base != 0u ? g_guest_fs_base : interrupted_fs);
    complete_syscall(state, rip, result);
#else
''',
        'signal exit FS restore',
    )
    source = replace_once(
        source,
        '''void install_sigill_handler(void) {
    void *altstack = mmap(NULL, HRT_ALTSTACK_SIZE, PROT_READ | PROT_WRITE,
''',
        '''void install_sigill_handler(void) {
    g_host_fs_base = read_fs_base();
    g_guest_fs_base = 0;
    void *altstack = mmap(NULL, HRT_ALTSTACK_SIZE, PROT_READ | PROT_WRITE,
''',
        'host FS initialization',
    )

    output = pathlib.Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
