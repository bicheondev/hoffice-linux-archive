#!/usr/bin/env python3
"""Teach generated x86-64 Darwin syscall wrappers that RDX is a return register.

XNU writes the secondary return value to RDX for integer-returning syscalls and
clears RDX for ssize_t/size_t/off_t/address returns.  Treating RDX as preserved
lets Clang keep live C values there across ``syscall``.  The getdents64 bridge
then compares its byte count against an RDX-hosted capacity that XNU has just
cleared, spuriously returning EIO.  This fail-closed source transform makes
that ABI fact explicit for every generated wrapper used by M3.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")

    syscall0 = '''static inline int64_t raw_bsd_syscall0(uint64_t number) {
    uint64_t result;
    unsigned char failed;
    __asm__ volatile(
        "syscall\\n\\t"
        "setc %1"
        : "=a"(result), "=qm"(failed)
        : "0"(DARWIN_BSD_SYSCALL(number))
        : "rcx", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}
'''
    syscall0_fixed = '''static inline int64_t raw_bsd_syscall0(uint64_t number) {
    uint64_t result;
    unsigned char failed;
    __asm__ volatile(
        "syscall\\n\\t"
        "setc %1"
        : "=a"(result), "=qm"(failed)
        : "0"(DARWIN_BSD_SYSCALL(number))
        : "rcx", "rdx", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}
'''
    text = replace_once(text, syscall0, syscall0_fixed,
                        "zero-argument Darwin syscall ABI")

    syscall3 = '''static inline int64_t raw_bsd_syscall3(uint64_t number,
                                       uint64_t argument1,
                                       uint64_t argument2,
                                       uint64_t argument3) {
    uint64_t result;
    unsigned char failed;
    __asm__ volatile(
        "syscall\\n\\t"
        "setc %1"
        : "=a"(result), "=qm"(failed)
        : "0"(DARWIN_BSD_SYSCALL(number)),
          "D"(argument1), "S"(argument2), "d"(argument3)
        : "rcx", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}
'''
    syscall3_fixed = '''static inline int64_t raw_bsd_syscall3(uint64_t number,
                                       uint64_t argument1,
                                       uint64_t argument2,
                                       uint64_t argument3) {
    uint64_t result;
    unsigned char failed;
    uint64_t argument3_register = argument3;
    __asm__ volatile(
        "syscall\\n\\t"
        "setc %1"
        : "=a"(result), "=qm"(failed), "+d"(argument3_register)
        : "0"(DARWIN_BSD_SYSCALL(number)),
          "D"(argument1), "S"(argument2)
        : "rcx", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}
'''
    text = replace_once(text, syscall3, syscall3_fixed,
                        "three-argument Darwin syscall ABI")

    syscall4 = '''static inline int64_t raw_bsd_syscall4(uint64_t number,
                                       uint64_t argument1,
                                       uint64_t argument2,
                                       uint64_t argument3,
                                       uint64_t argument4) {
    uint64_t result;
    unsigned char failed;
    __asm__ volatile(
        "movq %[argument4], %%r10\\n\\t"
        "syscall\\n\\t"
        "setc %1"
        : "=a"(result), "=qm"(failed)
        : "0"(DARWIN_BSD_SYSCALL(number)),
          "D"(argument1), "S"(argument2), "d"(argument3),
          [argument4] "r"(argument4)
        : "rcx", "r10", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}
'''
    syscall4_fixed = '''static inline int64_t raw_bsd_syscall4(uint64_t number,
                                       uint64_t argument1,
                                       uint64_t argument2,
                                       uint64_t argument3,
                                       uint64_t argument4) {
    uint64_t result;
    unsigned char failed;
    uint64_t argument3_register = argument3;
    __asm__ volatile(
        "movq %[argument4], %%r10\\n\\t"
        "syscall\\n\\t"
        "setc %1"
        : "=a"(result), "=qm"(failed), "+d"(argument3_register)
        : "0"(DARWIN_BSD_SYSCALL(number)),
          "D"(argument1), "S"(argument2),
          [argument4] "r"(argument4)
        : "rcx", "r10", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}
'''
    text = replace_once(text, syscall4, syscall4_fixed,
                        "four-argument Darwin syscall ABI")

    set_gs = '''static inline uintptr_t raw_set_gs(uintptr_t base) {
    uintptr_t result;
    __asm__ volatile(
        "syscall"
        : "=a"(result)
        : "0"(DARWIN_MACHDEP_SET_GS), "D"(base)
        : "rcx", "r11", "cc", "memory");
    return result;
}
'''
    set_gs_fixed = '''static inline uintptr_t raw_set_gs(uintptr_t base) {
    uintptr_t result;
    __asm__ volatile(
        "syscall"
        : "=a"(result)
        : "0"(DARWIN_MACHDEP_SET_GS), "D"(base)
        : "rcx", "rdx", "r11", "cc", "memory");
    return result;
}
'''
    text = replace_once(text, set_gs, set_gs_fixed,
                        "Darwin GS syscall ABI")

    raw_exit = '''        : "a"(DARWIN_BSD_SYSCALL(DARWIN_SYS_EXIT)), "D"((uint64_t)status)
        : "rcx", "r11", "cc", "memory");
'''
    raw_exit_fixed = '''        : "a"(DARWIN_BSD_SYSCALL(DARWIN_SYS_EXIT)), "D"((uint64_t)status)
        : "rcx", "rdx", "r11", "cc", "memory");
'''
    text = replace_once(text, raw_exit, raw_exit_fixed,
                        "Darwin exit syscall ABI")

    if text.count('"rdx", "r11", "cc", "memory"') < 3:
        raise SystemExit("RDX return-register annotations were not retained")
    if text.count('"+d"(argument3_register)') != 2:
        raise SystemExit("expected exactly two RDX input/output constraints")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
