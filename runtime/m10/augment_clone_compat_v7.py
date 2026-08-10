#!/usr/bin/env python3
"""Restore the real Darwin pthread TSD base around Linux clone children.

Rosetta returns ``KERN_FAILURE`` for ``thread_get_state`` with
``x86_THREAD_FULL_STATE64``.  The previous fallback used ``pthread_self()`` as
if it were the GS base.  Darwin actually points GS at the pthread TSD array;
on the current runner ``pthread_layout_offsets`` reports an offset of 224
bytes, and ``*(pthread_self() + 224) == pthread_self()``.

Passing the pthread object rather than its TSD base to
``thread_fast_set_cthread_self64`` left libpthread cleanup with corrupt direct
TSD.  The guest thread itself completed, but the host callback then trapped in
libpthread.  This fail-closed transform derives the TSD base through Apple's
exported pthread layout SPI, verifies slot zero against ``pthread_self()``, and
uses that address for both the main runtime and every pthread-backed clone.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="hrt-m10-clone-v7-") as temporary:
        intermediate = Path(temporary) / "clone-v6.c"
        subprocess.run(
            [
                sys.executable,
                "runtime/m10/augment_clone_compat_v6.py",
                str(args.source),
                str(intermediate),
            ],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "HRT M10 HOST GS: pthread-layout-derived" in text:
        raise SystemExit("Rosetta pthread TSD-base repair is already present")

    text = replace_once(
        text,
        '#include <dirent.h>\n',
        '#include <dirent.h>\n#include <dlfcn.h>\n',
        "dlsym include",
    )

    old_capture = '''static uintptr_t capture_host_gs_base(void) {
    x86_thread_full_state64_t state;
    mach_msg_type_number_t count = x86_THREAD_FULL_STATE64_COUNT;
    memset(&state, 0, sizeof(state));
    mach_port_t thread = mach_thread_self();
    kern_return_t result = thread_get_state(
        thread, x86_THREAD_FULL_STATE64,
        (thread_state_t)&state, &count);
    (void)mach_port_deallocate(mach_task_self(), thread);
    if (result == KERN_SUCCESS && state.__gsbase != 0u) {
        return (uintptr_t)state.__gsbase;
    }
    return (uintptr_t)pthread_self();
}
'''
    new_capture = r'''typedef struct HrtPthreadLayoutOffsets {
    uint16_t version;
    uint16_t pthread_tsd_base_offset;
    uint16_t pthread_tsd_base_address_offset;
    uint16_t pthread_tsd_entry_size;
} HrtPthreadLayoutOffsets;

static uintptr_t m10_pthread_tsd_base_from_layout(pthread_t self) {
    const HrtPthreadLayoutOffsets *layout =
        (const HrtPthreadLayoutOffsets *)dlsym(
            RTLD_DEFAULT, "pthread_layout_offsets");
    if (layout == NULL || layout->version == 0u ||
        layout->pthread_tsd_entry_size != sizeof(void *)) {
        return 0u;
    }

    const uintptr_t pthread_address = (uintptr_t)self;
    uintptr_t base = 0u;
    if (layout->pthread_tsd_base_offset != 0u) {
        base = pthread_address +
            (uintptr_t)layout->pthread_tsd_base_offset;
    } else if (layout->pthread_tsd_base_address_offset != 0u) {
        const uintptr_t *base_address = (const uintptr_t *)(
            pthread_address +
            (uintptr_t)layout->pthread_tsd_base_address_offset);
        base = *base_address;
    }

    if (base == 0u || *(const uintptr_t *)(uintptr_t)base != pthread_address) {
        return 0u;
    }
    return base;
}

static uintptr_t capture_host_gs_base(void) {
    x86_thread_full_state64_t state;
    mach_msg_type_number_t count = x86_THREAD_FULL_STATE64_COUNT;
    memset(&state, 0, sizeof(state));
    mach_port_t thread = mach_thread_self();
    kern_return_t result = thread_get_state(
        thread, x86_THREAD_FULL_STATE64,
        (thread_state_t)&state, &count);
    (void)mach_port_deallocate(mach_task_self(), thread);
    if (result == KERN_SUCCESS && state.__gsbase != 0u) {
        return (uintptr_t)state.__gsbase;
    }

    /* HRT M10 HOST GS: pthread-layout-derived */
    return m10_pthread_tsd_base_from_layout(pthread_self());
}
'''
    text = replace_once(text, old_capture, new_capture,
                        "Darwin pthread TSD-base capture")

    required = {
        '#include <dlfcn.h>': 1,
        'HRT M10 HOST GS: pthread-layout-derived': 1,
        'm10_pthread_tsd_base_from_layout(': 2,
        'pthread_layout_offsets': 1,
        'pthread_tsd_base_offset': 3,
        'pthread_tsd_base_address_offset': 3,
        'pthread_tsd_entry_size': 2,
        'return (uintptr_t)pthread_self();': 0,
        'case LINUX_SYS_CLONE:': 1,
        'case LINUX_SYS_CHDIR:': 1,
        'm10_schedule_clone_thread_exit(': 2,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"clone-v7 marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
