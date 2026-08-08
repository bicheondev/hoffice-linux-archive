#!/usr/bin/env python3
"""Add the first real Linux pthread-style clone bridge to the clean-room host.

The exact HWord main window now survives with all earlier filesystem and wakeup
syscalls translated.  Its remaining Linux calls are ``chdir`` and the standard
NPTL clone flag set ``0x3d0f00``.  This transform implements those boundaries
rather than hiding them:

* absolute and relative chdir remain confined to the mounted guest root;
* getcwd reports the corresponding Linux guest path;
* pthread-style clone creates a detached macOS x86-64 host thread;
* the child resumes at the instruction after clone with RAX=0, the supplied
  Linux stack, TLS/GS base, floating-point state and callee-saved registers;
* parent/child TID stores, gettid, set_tid_address, tgkill and thread exit use
  a fixed lock-free thread table; and
* per-thread signal/TLS state is selected from the current GS base, avoiding
  Mach-O TLS while GS is owned by the Linux guest.

The implementation deliberately accepts only the exact shared-memory NPTL flag
set observed in HWord.  Process-style clone, namespaces and fork semantics fail
closed with EINVAL.  pthread_create is invoked only after the bridge has
restored the host GS context.
"""
from __future__ import annotations

import argparse
from pathlib import Path


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

    text = args.source.read_text(encoding="utf-8")
    if "HRT M10 CLONE:" in text:
        raise SystemExit("M10 clone compatibility is already present")

    text = replace_once(
        text,
        '#include "linux_abi.h"\n',
        '#include "linux_abi.h"\n#include "clone_trampoline.h"\n',
        "clone trampoline include",
    )
    text = replace_once(
        text,
        "#include <poll.h>\n#include <sys/event.h>\n",
        "#include <poll.h>\n#include <sched.h>\n#include <sys/event.h>\n",
        "scheduler header",
    )

    syscall_anchor = (
        "#ifndef LINUX_SYS_SOCKET\n"
        "#define LINUX_SYS_SOCKET UINT64_C(41)\n"
        "#endif\n"
    )
    syscall_constants = syscall_anchor + (
        "#ifndef LINUX_SYS_CLONE\n"
        "#define LINUX_SYS_CLONE UINT64_C(56)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_CHDIR\n"
        "#define LINUX_SYS_CHDIR UINT64_C(80)\n"
        "#endif\n"
        "#define M10_CLONE_VM UINT64_C(0x00000100)\n"
        "#define M10_CLONE_FS UINT64_C(0x00000200)\n"
        "#define M10_CLONE_FILES UINT64_C(0x00000400)\n"
        "#define M10_CLONE_SIGHAND UINT64_C(0x00000800)\n"
        "#define M10_CLONE_THREAD UINT64_C(0x00010000)\n"
        "#define M10_CLONE_SYSVSEM UINT64_C(0x00040000)\n"
        "#define M10_CLONE_SETTLS UINT64_C(0x00080000)\n"
        "#define M10_CLONE_PARENT_SETTID UINT64_C(0x00100000)\n"
        "#define M10_CLONE_CHILD_CLEARTID UINT64_C(0x00200000)\n"
        "#define M10_NPTL_CLONE_FLAGS (M10_CLONE_VM | M10_CLONE_FS | "
        "M10_CLONE_FILES | M10_CLONE_SIGHAND | M10_CLONE_THREAD | "
        "M10_CLONE_SYSVSEM | M10_CLONE_SETTLS | "
        "M10_CLONE_PARENT_SETTID | M10_CLONE_CHILD_CLEARTID)\n"
    )
    text = replace_once(text, syscall_anchor, syscall_constants,
                        "clone and chdir constants")

    globals_anchor = '''static volatile sig_atomic_t g_in_handler;
static volatile uint64_t g_last_linux_syscall;
static volatile uint64_t g_last_linux_syscall_rip;
static volatile sig_atomic_t g_guest_tls_active;
static uintptr_t g_host_gs_base;
static uintptr_t g_guest_fs_base;
static char g_root[PATH_MAX];
static char g_guest_program[PATH_MAX];
'''
    globals_replacement = r'''#define M10_MAX_GUEST_THREADS 32u
#define M10_THREAD_TRACE_LIMIT 128u

static HrtM10CloneContext g_m10_main_thread;
static HrtM10CloneContext g_m10_clone_threads[M10_MAX_GUEST_THREADS];
static volatile uint64_t g_m10_next_linux_tid = UINT64_C(10000);
static unsigned int g_m10_thread_trace_count;

static inline uintptr_t m10_read_gs_base(void) {
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

#define g_in_handler (m10_current_thread_state()->in_handler)
#define g_last_linux_syscall (m10_current_thread_state()->last_linux_syscall)
#define g_last_linux_syscall_rip \
    (m10_current_thread_state()->last_linux_syscall_rip)
#define g_guest_tls_active \
    (m10_current_thread_state()->guest_tls_active)
#define g_host_gs_base (m10_current_thread_state()->host_gs)
#define g_guest_fs_base (m10_current_thread_state()->guest_gs)
#define g_clear_child_tid (m10_current_thread_state()->clear_child_tid)
#define g_linux_tid (m10_current_thread_state()->linux_tid)

static char g_root[PATH_MAX];
static char g_root_real[PATH_MAX];
static char g_guest_program[PATH_MAX];
'''
    text = replace_once(text, globals_anchor, globals_replacement,
                        "per-thread bridge state")
    text = replace_once(
        text,
        "static uintptr_t g_clear_child_tid;\n",
        "",
        "legacy clear-child-TID global",
    )

    clone_support_anchor = '''static int translate_guest_path(const char *guest_path,
                                char *host_path, size_t capacity) {
'''
    clone_support = r'''static uintptr_t capture_host_gs_base(void);

static void m10_trace_thread(const char *stage, int64_t result,
                             uint64_t flags, uint64_t tid,
                             uint64_t stack, uint64_t tls) {
    if (g_m10_thread_trace_count >= M10_THREAD_TRACE_LIMIT) return;
    ++g_m10_thread_trace_count;
    char buffer[448];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M10 CLONE: stage=");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), stage);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " result=");
    if (result < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-result));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)result);
    }
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " flags=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), flags);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " tid=");
    cursor = trace_append_decimal(buffer, cursor, sizeof(buffer), tid);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " stack=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), stack);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " tls=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), tls);
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    raw_write_literal(buffer, cursor < sizeof(buffer) ? cursor : sizeof(buffer));
}

static HrtM10CloneContext *m10_allocate_clone_context(void) {
    for (size_t index = 0u; index < M10_MAX_GUEST_THREADS; ++index) {
        HrtM10CloneContext *candidate = &g_m10_clone_threads[index];
        if (__sync_bool_compare_and_swap(&candidate->active, 0u, 1u)) {
            memset((unsigned char *)candidate + sizeof(candidate->active),
                   0, sizeof(*candidate) - sizeof(candidate->active));
            return candidate;
        }
    }
    return NULL;
}

static int m10_install_thread_altstack(void) {
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

static void *m10_clone_thread_start(void *opaque) {
    HrtM10CloneContext *context = (HrtM10CloneContext *)opaque;
    while (__atomic_load_n(&context->ready, __ATOMIC_ACQUIRE) == 0u)
        sched_yield();

    context->host_gs = capture_host_gs_base();
    if (context->host_gs == 0u || m10_install_thread_altstack() != 0) {
        if (context->child_tid_address != 0u) {
            __atomic_store_n(
                (uint32_t *)(uintptr_t)context->child_tid_address,
                0u, __ATOMIC_RELEASE);
        }
        context->active = 0u;
        return NULL;
    }

    context->in_handler = 0u;
    context->last_linux_syscall = 0u;
    context->last_linux_syscall_rip = 0u;
    context->guest_gs = context->guest_gs != 0u
        ? context->guest_gs : context->guest_rsp;
    context->guest_tls_active = 1u;
    context->clear_child_tid = context->child_tid_address;
    if (context->child_tid_address != 0u) {
        __atomic_store_n(
            (uint32_t *)(uintptr_t)context->child_tid_address,
            (uint32_t)context->linux_tid, __ATOMIC_RELEASE);
    }

    m10_trace_thread("child-enter", (int64_t)context->linux_tid,
                     context->flags, context->linux_tid,
                     context->guest_rsp, context->guest_gs);
    (void)raw_set_gs(context->guest_gs);
    hrt_m10_enter_clone_child(context);
}

static void m10_exit_current_guest_thread(int status)
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

static int64_t m10_host_clone_bridge(x86_thread_state64_t *state,
                                     uint64_t trapped_rip) {
    const uint64_t flags = state->__rdi;
    if (flags != M10_NPTL_CLONE_FLAGS || state->__rsi == 0u ||
        state->__rdx == 0u || state->__r10 == 0u || state->__r8 == 0u) {
        m10_trace_thread("reject", -LINUX_EINVAL, flags, 0u,
                         state->__rsi, state->__r8);
        return -LINUX_EINVAL;
    }

    HrtM10CloneContext *context = m10_allocate_clone_context();
    if (context == NULL) {
        m10_trace_thread("capacity", -LINUX_EAGAIN, flags, 0u,
                         state->__rsi, state->__r8);
        return -LINUX_EAGAIN;
    }

    context->flags = flags;
    context->linux_tid = __sync_fetch_and_add(
        &g_m10_next_linux_tid, UINT64_C(1));
    context->resume_rip = trapped_rip + 2u;
    context->guest_rsp = state->__rsi;
    context->guest_rflags = state->__rflags;
    context->guest_rbx = state->__rbx;
    context->guest_rbp = state->__rbp;
    context->guest_r12 = state->__r12;
    context->guest_r13 = state->__r13;
    context->guest_r14 = state->__r14;
    context->guest_r15 = state->__r15;
    context->guest_rdi = state->__rdi;
    context->guest_rsi = state->__rsi;
    context->guest_rdx = state->__rdx;
    context->guest_r10 = state->__r10;
    context->guest_r8 = state->__r8;
    context->guest_r9 = state->__r9;
    context->guest_gs = state->__r8;
    context->parent_tid_address = state->__rdx;
    context->child_tid_address = state->__r10;
    __asm__ volatile("fxsave64 %0" : "=m"(context->fxsave));

    __atomic_store_n(
        (uint32_t *)(uintptr_t)context->parent_tid_address,
        (uint32_t)context->linux_tid, __ATOMIC_RELEASE);

    pthread_t thread;
    uintptr_t guest = switch_to_host_context();
    int host_result = pthread_create(
        &thread, NULL, m10_clone_thread_start, context);
    if (host_result == 0)
        host_result = pthread_detach(thread);
    if (host_result == 0) {
        static_assert(sizeof(thread) <= sizeof(context->host_thread_bits),
                      "pthread_t must fit in clone context");
        memcpy(&context->host_thread_bits, &thread, sizeof(thread));
    }
    restore_guest_context(guest);

    if (host_result != 0) {
        __atomic_store_n(
            (uint32_t *)(uintptr_t)context->parent_tid_address,
            0u, __ATOMIC_RELEASE);
        context->active = 0u;
        int64_t result = -(int64_t)linux_errno_from_host(host_result);
        m10_trace_thread("pthread-error", result, flags,
                         context->linux_tid, context->guest_rsp,
                         context->guest_gs);
        return result;
    }

    __atomic_store_n(&context->ready, 1u, __ATOMIC_RELEASE);
    m10_trace_thread("parent-return", (int64_t)context->linux_tid,
                     flags, context->linux_tid, context->guest_rsp,
                     context->guest_gs);
    return (int64_t)context->linux_tid;
}

static HrtM10CloneContext *m10_thread_for_tid(uint64_t tid) {
    if (g_m10_main_thread.active != 0u &&
        g_m10_main_thread.linux_tid == tid) {
        return &g_m10_main_thread;
    }
    for (size_t index = 0u; index < M10_MAX_GUEST_THREADS; ++index) {
        if (g_m10_clone_threads[index].active != 0u &&
            g_m10_clone_threads[index].linux_tid == tid) {
            return &g_m10_clone_threads[index];
        }
    }
    return NULL;
}

static int translate_guest_path(const char *guest_path,
                                char *host_path, size_t capacity) {
'''
    text = replace_once(text, clone_support_anchor, clone_support,
                        "clone runtime and state table")

    chdir_anchor = '''static int64_t bridge_getcwd(char *buffer, size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    if (size < 2u) return -LINUX_ERANGE;
    buffer[0] = '/';
    buffer[1] = '\0';
    return 2;
}
'''
    chdir_bridge = r'''static int64_t host_chdir_bridge(const char *guest_path) {
    if (guest_path == NULL) return -LINUX_EFAULT;

    uintptr_t guest = switch_to_host_context();
    char translated[PATH_MAX];
    char resolved[PATH_MAX];
    if (translate_guest_path(guest_path, translated,
                             sizeof(translated)) != 0 ||
        realpath(translated, resolved) == NULL) {
        int saved_errno = errno;
        restore_guest_context(guest);
        return -(int64_t)linux_errno_from_host(
            saved_errno != 0 ? saved_errno : ENOENT);
    }

    size_t root_length = strlen(g_root_real);
    if (strncmp(resolved, g_root_real, root_length) != 0 ||
        (resolved[root_length] != '\0' && resolved[root_length] != '/')) {
        restore_guest_context(guest);
        return -LINUX_EACCES;
    }

    errno = 0;
    int host_result = chdir(resolved);
    int saved_errno = errno;
    restore_guest_context(guest);
    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    m10_trace_thread("chdir", result, 0u, g_linux_tid, 0u, 0u);
    return result;
}

static int64_t bridge_getcwd(char *buffer, size_t size) {
    if (buffer == NULL) return -LINUX_EFAULT;
    uintptr_t guest = switch_to_host_context();
    char host_cwd[PATH_MAX];
    errno = 0;
    char *host_result = getcwd(host_cwd, sizeof(host_cwd));
    int saved_errno = errno;
    restore_guest_context(guest);
    if (host_result == NULL)
        return -(int64_t)linux_errno_from_host(saved_errno);

    const size_t root_length = strlen(g_root_real);
    if (strncmp(host_cwd, g_root_real, root_length) != 0 ||
        (host_cwd[root_length] != '\0' && host_cwd[root_length] != '/')) {
        return -LINUX_EACCES;
    }
    const char *relative = host_cwd + root_length;
    if (relative[0] == '\0') relative = "/";
    const size_t length = strlen(relative) + 1u;
    if (length > size) return -LINUX_ERANGE;
    memcpy(buffer, relative, length);
    return (int64_t)length;
}
'''
    text = replace_once(text, chdir_anchor, chdir_bridge,
                        "guest chdir and getcwd")

    tgkill_anchor = '''static int64_t host_tgkill_bridge(int process_id, int thread_id,
                                  int linux_signal) {
    uintptr_t guest = switch_to_host_context();
    pid_t self = getpid();
    restore_guest_context(guest);
    if (process_id != (int)self || thread_id != (int)self) {
        return -LINUX_ESRCH;
    }

    int host_signal = host_signal_from_linux(linux_signal);
    if (host_signal < 0) return -LINUX_EINVAL;
    if (host_signal == 0) return 0;

    guest = switch_to_host_context();
    errno = 0;
    int result = kill(self, host_signal);
    int saved_errno = errno;
    restore_guest_context(guest);
    if (result != 0) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }
    return 0;
}
'''
    tgkill_replacement = r'''static int64_t host_tgkill_bridge(int process_id, int thread_id,
                                  int linux_signal) {
    uintptr_t guest = switch_to_host_context();
    pid_t self = getpid();
    restore_guest_context(guest);
    if (process_id != (int)self) return -LINUX_ESRCH;

    HrtM10CloneContext *target = m10_thread_for_tid(
        (uint64_t)(unsigned int)thread_id);
    if (target == NULL) return -LINUX_ESRCH;
    int host_signal = host_signal_from_linux(linux_signal);
    if (host_signal < 0) return -LINUX_EINVAL;
    if (host_signal == 0) return 0;

    pthread_t thread;
    memset(&thread, 0, sizeof(thread));
    memcpy(&thread, &target->host_thread_bits, sizeof(thread));
    guest = switch_to_host_context();
    int result = pthread_kill(thread, host_signal);
    restore_guest_context(guest);
    return result == 0 ? 0 :
        -(int64_t)linux_errno_from_host(result);
}
'''
    text = replace_once(text, tgkill_anchor, tgkill_replacement,
                        "thread-aware tgkill")

    text = replace_once(
        text,
        "        case LINUX_SYS_SOCKET:\n",
        "        case LINUX_SYS_CLONE:\n"
        "            result = m10_host_clone_bridge(state, rip);\n"
        "            break;\n"
        "        case LINUX_SYS_SOCKET:\n",
        "Linux clone dispatch",
    )
    text = replace_once(
        text,
        "        case LINUX_SYS_MKDIR:\n",
        "        case LINUX_SYS_CHDIR:\n"
        "            result = host_chdir_bridge(\n"
        "                (const char *)(uintptr_t)state->__rdi);\n"
        "            break;\n"
        "        case LINUX_SYS_MKDIR:\n",
        "Linux chdir dispatch",
    )

    exit_anchor = '''        case LINUX_SYS_EXIT:
        case LINUX_SYS_EXIT_GROUP:
            raw_exit((int)(state->__rdi & 0xffu));
'''
    exit_replacement = '''        case LINUX_SYS_EXIT:
            m10_exit_current_guest_thread(
                (int)(state->__rdi & 0xffu));
        case LINUX_SYS_EXIT_GROUP:
            raw_exit((int)(state->__rdi & 0xffu));
'''
    text = replace_once(text, exit_anchor, exit_replacement,
                        "thread-local exit semantics")
    text = replace_once(
        text,
        "        case LINUX_SYS_GETTID:\n"
        "            result = raw_bsd_syscall0(DARWIN_SYS_GETPID);\n"
        "            break;\n",
        "        case LINUX_SYS_GETTID:\n"
        "            result = (int64_t)g_linux_tid;\n"
        "            break;\n",
        "thread-local gettid",
    )

    init_anchor = '''    g_host_gs_base = capture_host_gs_base();
    if (g_host_gs_base == 0u) {
        errno = 0;
        fatal("could not capture host GS base");
    }
'''
    init_replacement = '''    memset(&g_m10_main_thread, 0, sizeof(g_m10_main_thread));
    g_m10_main_thread.active = 1u;
    g_m10_main_thread.ready = 1u;
    g_host_gs_base = capture_host_gs_base();
    if (g_host_gs_base == 0u) {
        errno = 0;
        fatal("could not capture host GS base");
    }
    g_linux_tid = (uint64_t)(unsigned int)getpid();
    pthread_t main_thread = pthread_self();
    static_assert(sizeof(main_thread) <=
                      sizeof(g_m10_main_thread.host_thread_bits),
                  "pthread_t must fit in main thread state");
    memcpy(&g_m10_main_thread.host_thread_bits,
           &main_thread, sizeof(main_thread));
    if (realpath(root, g_root_real) == NULL) {
        fatal("resolve M10 guest root");
    }
'''
    text = replace_once(text, init_anchor, init_replacement,
                        "main thread and real guest root initialization")

    required = {
        "case LINUX_SYS_CLONE:": 1,
        "case LINUX_SYS_CHDIR:": 1,
        "m10_host_clone_bridge(": 2,
        "m10_clone_thread_start(": 2,
        "hrt_m10_enter_clone_child(": 1,
        "HRT M10 CLONE:": 1,
        "rdgsbase": 1,
        "g_root_real": 8,
        "m10_exit_current_guest_thread(": 3,
        "case LINUX_SYS_GETTID:": 1,
        "pthread_create(": 1,
        "pthread_exit(NULL)": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"clone marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
