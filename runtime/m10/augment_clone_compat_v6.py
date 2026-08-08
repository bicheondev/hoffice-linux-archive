#!/usr/bin/env python3
"""Complete pthread-backed Linux clone entry and normal host return.

The mature v2 generator supplies guest-confined chdir/getcwd, a fixed clone
context table and Rosetta-safe signal-stack ownership.  This final transform
keeps those boundaries and changes only clone-thread entry/exit mechanics:

* inherited synchronous guest trap signals are unblocked before guest entry;
* GS is switched only inside the already-entered assembly leaf;
* Linux ``exit`` schedules an assembly return trampoline through ucontext; and
* that trampoline restores host GS, FPU/vector state, stack and all Darwin
  x86-64 callee-saved registers, then returns normally from the pthread start
  callback instead of invoking pthread_exit on guest or alternate-signal
  memory.

The process main thread still maps Linux exit/exit_group directly to process
exit.  Every source edit is exact-anchor and fail closed.
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

    with tempfile.TemporaryDirectory(prefix="hrt-m10-clone-v6-") as temporary:
        intermediate = Path(temporary) / "clone-v2.c"
        subprocess.run(
            [
                sys.executable,
                "runtime/m10/augment_clone_compat_v2.py",
                str(args.source),
                str(intermediate),
            ],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    helper_anchor = '''static void *m10_clone_thread_start(void *opaque) {
'''
    helper = r'''static int m10_unblock_guest_trap_signals(void) {
    sigset_t signals;
    if (sigemptyset(&signals) != 0) return errno != 0 ? errno : EINVAL;
    const int trapped_signals[] = {
        SIGILL, SIGTRAP, SIGSEGV, SIGBUS, SIGABRT, SIGFPE,
    };
    for (size_t index = 0u;
         index < sizeof(trapped_signals) / sizeof(trapped_signals[0]);
         ++index) {
        if (sigaddset(&signals, trapped_signals[index]) != 0)
            return errno != 0 ? errno : EINVAL;
    }
    return pthread_sigmask(SIG_UNBLOCK, &signals, NULL);
}

static void *m10_clone_thread_start(void *opaque) {
'''
    text = replace_once(text, helper_anchor, helper,
                        "clone child signal-mask helper")

    setup_anchor = '''    context->host_gs = capture_host_gs_base();
    if (context->host_gs == 0u ||
        m10_install_thread_altstack(context) != 0) {
'''
    setup_replacement = '''    context->host_gs = capture_host_gs_base();
    const int trap_mask_result = m10_unblock_guest_trap_signals();
    if (context->host_gs == 0u || trap_mask_result != 0 ||
        m10_install_thread_altstack(context) != 0) {
'''
    text = replace_once(text, setup_anchor, setup_replacement,
                        "clone child trap-mask setup")

    entry_anchor = '''    m10_trace_thread("child-enter", (int64_t)context->linux_tid,
                     context->flags, context->linux_tid,
                     context->guest_rsp, context->guest_gs);
    (void)raw_set_gs(context->guest_gs);
    hrt_m10_enter_clone_child(context);
}
'''
    entry_replacement = r'''    m10_trace_thread("child-enter", (int64_t)context->linux_tid,
                     context->flags, context->linux_tid,
                     context->guest_rsp, context->guest_gs);

    /* The assembly leaf owns both the guest TLS switch and host restoration. */
    hrt_m10_enter_clone_child(context);

    /* Normal return now executes on the original pthread stack and host GS. */
    const int status = (int)(context->exit_status & UINT64_C(0xff));
    const uint64_t tid = context->linux_tid;
    const uint64_t clear_address = context->clear_child_tid;
    if (clear_address != 0u) {
        __atomic_store_n((uint32_t *)(uintptr_t)clear_address,
                         0u, __ATOMIC_RELEASE);
    }
    m10_trace_thread("child-exit", status, context->flags, tid,
                     context->guest_rsp, context->guest_gs);
    context->active = 0u;
    return NULL;
}
'''
    text = replace_once(text, entry_anchor, entry_replacement,
                        "normal pthread callback return")

    old_exit = '''static void m10_exit_current_guest_thread(int status)
    __attribute__((noreturn));

static void m10_exit_current_guest_thread(int status) {
    HrtM10CloneContext *context = m10_current_thread_state();
    if (context == &g_m10_main_thread) raw_exit(status);

    const uint64_t tid = context->linux_tid;
    const uint64_t clear_address = context->clear_child_tid;
    uintptr_t guest = switch_to_host_context();
    if (clear_address != 0u) {
        __atomic_store_n((uint32_t *)(uintptr_t)clear_address,
                         0u, __ATOMIC_RELEASE);
    }
    context->active = 0u;
    m10_trace_thread("child-exit", status, context->flags, tid,
                     context->guest_rsp, context->guest_gs);
    (void)guest;
    pthread_exit(NULL);
    __builtin_unreachable();
}
'''
    new_exit = r'''static void m10_schedule_clone_thread_exit(
        x86_thread_state64_t *state, int status) {
    HrtM10CloneContext *context = m10_current_thread_state();
    if (context == &g_m10_main_thread) raw_exit(status);

    /*
     * Signal return enters an assembly leaf on the current signal stack.  The
     * leaf stores the status, restores the saved host ABI frame and returns
     * from hrt_m10_enter_clone_child to the ordinary pthread callback.
     */
    state->__rip = (uint64_t)(uintptr_t)hrt_m10_exit_clone_child;
    state->__rdi = (uint64_t)(uintptr_t)context;
    state->__rsi = (uint64_t)(unsigned int)status;
    state->__rax = 0u;
    context->exit_status = (uint64_t)(unsigned int)status;
    context->in_handler = 0u;
}
'''
    text = replace_once(text, old_exit, new_exit,
                        "deferred normal-return clone exit")

    old_dispatch = '''        case LINUX_SYS_EXIT:
        case LINUX_SYS_EXIT_GROUP:
            raw_exit((int)(state->__rdi & 0xffu));
'''
    new_dispatch = '''        case LINUX_SYS_EXIT:
            m10_schedule_clone_thread_exit(
                state, (int)(state->__rdi & 0xffu));
            return;
        case LINUX_SYS_EXIT_GROUP:
            raw_exit((int)(state->__rdi & 0xffu));
'''
    text = replace_once(text, old_dispatch, new_dispatch,
                        "thread-local Linux exit dispatch")

    required = {
        "hrt_m10_enter_clone_child(context);": 1,
        "m10_unblock_guest_trap_signals(": 2,
        "pthread_sigmask(SIG_UNBLOCK": 1,
        "trap_mask_result != 0": 1,
        "m10_schedule_clone_thread_exit(": 2,
        "hrt_m10_exit_clone_child": 1,
        "context->exit_status =": 1,
        "Normal return now executes on the original pthread stack": 1,
        "pthread_exit(": 0,
        "(void)raw_set_gs(context->guest_gs);": 0,
        "case LINUX_SYS_CLONE:": 1,
        "case LINUX_SYS_CHDIR:": 1,
        "pthread_create(": 1,
        'm10_trace_thread("child-exit"': 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"clone-v6 marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
