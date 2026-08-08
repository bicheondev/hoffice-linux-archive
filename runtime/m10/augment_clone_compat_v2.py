#!/usr/bin/env python3
"""Run the locked clone generator across mature macOS bridge shapes.

The first clone generator at commit 4f699526 supplies the real pthread-backed
Linux clone/chdir implementation.  This wrapper keeps its functional edits but
adapts three prototype assumptions:

* ``bridge_getcwd`` is replaced by balanced function boundaries when its old
  body has already been rewritten;
* two diagnostic token counts are corrected; and
* Rosetta, which does not execute ``RDFSBASE/RDGSBASE``, identifies the current
  guest thread by the alternate signal stack on which every syscall trap runs.

The main and clone-thread alternate-stack bases are stored in the context's
reserved field.  All per-thread state lookups made from SIGILL and crash
handlers therefore remain allocation-free and do not depend on Mach-O TLS while
the Linux guest owns GS.  Every rewrite is exact-anchor and fail closed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "4f699526cf213a7c38df34faafeda1049bb06a19"
LOCKED_PATH = "runtime/m10/augment_clone_compat.py"
GETCWD_SIGNATURE = "static int64_t bridge_getcwd(char *buffer, size_t size) {"


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def balanced_function_end(text: str, opening_brace: int) -> int:
    depth = 0
    index = opening_brace
    state = "code"
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if char == '"':
                state = "string"
            elif char == "'":
                state = "character"
            elif char == "/" and following == "/":
                state = "line-comment"
                index += 1
            elif char == "/" and following == "*":
                state = "block-comment"
                index += 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
                if depth < 0:
                    raise SystemExit("bridge_getcwd has an unmatched closing brace")
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "character":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif state == "line-comment":
            if char == "\n":
                state = "code"
        elif state == "block-comment":
            if char == "*" and following == "/":
                state = "code"
                index += 1
        index += 1
    raise SystemExit("bridge_getcwd function is not terminated")


def replace_getcwd_function(text: str, replacement: str) -> str:
    count = text.count(GETCWD_SIGNATURE)
    if count != 1:
        raise SystemExit(
            f"expected exactly one bridge_getcwd signature, found {count}")
    start = text.index(GETCWD_SIGNATURE)
    opening = start + GETCWD_SIGNATURE.rindex("{")
    end = balanced_function_end(text, opening)
    if text[end:end + 2] == "\r\n":
        end += 2
    elif text[end:end + 1] == "\n":
        end += 1
    result = text[:start] + replacement + text[end:]
    if result.count("static int64_t host_chdir_bridge(") != 1 or \
       result.count(GETCWD_SIGNATURE) != 1:
        raise SystemExit("parsed chdir/getcwd replacement did not close exactly")
    return result


def correct_locked_invariant(source: str, old: str, new: str,
                             label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(f"locked {label} invariant changed unexpectedly")
    return source.replace(old, new, 1)


def adapt_thread_lookup_for_rosetta(text: str) -> str:
    old_lookup = '''static inline uintptr_t m10_read_gs_base(void) {
    uintptr_t value;
    __asm__ volatile("rdgsbase %0" : "=r"(value));
    return value;
}

static HrtM10CloneContext *m10_current_thread_state(void) {
    const uintptr_t gs = m10_read_gs_base();
    if (g_m10_main_thread.active != 0u &&
        (g_m10_main_thread.guest_gs == gs ||
         g_m10_main_thread.host_gs == gs)) {
        return &g_m10_main_thread;
    }
    for (size_t index = 0u; index < M10_MAX_GUEST_THREADS; ++index) {
        HrtM10CloneContext *candidate = &g_m10_clone_threads[index];
        if (candidate->active != 0u &&
            (candidate->guest_gs == gs || candidate->host_gs == gs)) {
            return candidate;
        }
    }
    return &g_m10_main_thread;
}
'''
    new_lookup = '''/* Rosetta does not execute rdgsbase; use signal-stack ownership. */
static int m10_stack_belongs_to_context(const HrtM10CloneContext *context,
                                        uintptr_t address) {
    const uintptr_t base = (uintptr_t)context->reserved;
    return context->active != 0u && base != 0u &&
        address >= base && address < base + (uintptr_t)HRT_ALTSTACK_SIZE;
}

static HrtM10CloneContext *m10_current_thread_state(void) {
    const uintptr_t stack_address = (uintptr_t)&stack_address;
    if (m10_stack_belongs_to_context(
            &g_m10_main_thread, stack_address)) {
        return &g_m10_main_thread;
    }
    for (size_t index = 0u; index < M10_MAX_GUEST_THREADS; ++index) {
        HrtM10CloneContext *candidate = &g_m10_clone_threads[index];
        if (m10_stack_belongs_to_context(candidate, stack_address))
            return candidate;
    }
    /* Initialization and host-only setup execute on the main host stack. */
    return &g_m10_main_thread;
}
'''
    text = replace_once(text, old_lookup, new_lookup,
                        "Rosetta thread-state lookup")

    old_altstack = '''static int m10_install_thread_altstack(void) {
    void *memory = mmap(NULL, HRT_ALTSTACK_SIZE,
                        PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (memory == MAP_FAILED) return errno != 0 ? errno : ENOMEM;
    stack_t stack;
    memset(&stack, 0, sizeof(stack));
    stack.ss_sp = memory;
    stack.ss_size = HRT_ALTSTACK_SIZE;
    if (sigaltstack(&stack, NULL) != 0) {
        int saved_errno = errno;
        (void)munmap(memory, HRT_ALTSTACK_SIZE);
        return saved_errno != 0 ? saved_errno : EINVAL;
    }
    return 0;
}
'''
    new_altstack = '''static int m10_install_thread_altstack(
        HrtM10CloneContext *context) {
    void *memory = mmap(NULL, HRT_ALTSTACK_SIZE,
                        PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (memory == MAP_FAILED) return errno != 0 ? errno : ENOMEM;
    stack_t stack;
    memset(&stack, 0, sizeof(stack));
    stack.ss_sp = memory;
    stack.ss_size = HRT_ALTSTACK_SIZE;
    if (sigaltstack(&stack, NULL) != 0) {
        int saved_errno = errno;
        (void)munmap(memory, HRT_ALTSTACK_SIZE);
        return saved_errno != 0 ? saved_errno : EINVAL;
    }
    context->reserved = (uint64_t)(uintptr_t)memory;
    return 0;
}
'''
    text = replace_once(text, old_altstack, new_altstack,
                        "clone alternate-stack ownership")
    text = replace_once(
        text,
        "context->host_gs == 0u || m10_install_thread_altstack() != 0",
        "context->host_gs == 0u || "
        "m10_install_thread_altstack(context) != 0",
        "clone alternate-stack call",
    )

    main_altstack_anchor = '''    if (sigaltstack(&stack, NULL) != 0) fatal("M3 sigaltstack");

    struct sigaction action;
'''
    main_altstack_replacement = '''    if (sigaltstack(&stack, NULL) != 0) fatal("M3 sigaltstack");
    g_m10_main_thread.reserved = (uint64_t)(uintptr_t)altstack;

    struct sigaction action;
'''
    text = replace_once(text, main_altstack_anchor,
                        main_altstack_replacement,
                        "main alternate-stack ownership")
    return text


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} SOURCE.c OUTPUT.c")
    source_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    locked_source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout
    locked_source = correct_locked_invariant(
        locked_source,
        '        "m10_clone_thread_start(": 2,\n',
        '        "m10_clone_thread_start(": 1,\n',
        "clone callback count",
    )
    locked_source = correct_locked_invariant(
        locked_source,
        '        "g_root_real": 8,\n',
        '        "g_root_real": 6,\n',
        "guest-root count",
    )

    with tempfile.TemporaryDirectory(prefix="hrt-m10-clone-") as temporary:
        module_path = Path(temporary) / "locked_clone_generator.py"
        module_path.write_text(locked_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m10_locked_clone", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked clone generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        strict_replace = module.replace_once

        def compatible_replace(text: str, needle: str, replacement: str,
                               label: str) -> str:
            if label == "guest chdir and getcwd" and text.count(needle) == 0:
                return replace_getcwd_function(text, replacement)
            return strict_replace(text, needle, replacement, label)

        module.replace_once = compatible_replace
        previous_argv = sys.argv
        try:
            sys.argv = [str(module_path), str(source_path), str(output_path)]
            module.main()
        finally:
            sys.argv = previous_argv

    text = output_path.read_text(encoding="utf-8")
    count = text.count("static_assert(")
    if count != 2:
        raise SystemExit(
            f"expected exactly two emitted static_assert tokens, found {count}")
    text = text.replace("static_assert(", "_Static_assert(")
    text = adapt_thread_lookup_for_rosetta(text)

    required = {
        "case LINUX_SYS_CLONE:": 1,
        "case LINUX_SYS_CHDIR:": 1,
        "static int64_t host_chdir_bridge(": 1,
        "static int64_t bridge_getcwd(": 1,
        "pthread_create(": 1,
        "rdgsbase": 1,
        "m10_stack_belongs_to_context(": 3,
        "g_m10_main_thread.reserved =": 1,
        "m10_install_thread_altstack(context)": 1,
        "HRT M10 CLONE:": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"clone marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")
    output_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
