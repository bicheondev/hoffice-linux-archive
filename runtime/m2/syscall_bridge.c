#define _DARWIN_C_SOURCE 1
#include "syscall_internal.h"
#include "../m5/host_ui.h"

#include <dirent.h>
#include <errno.h>
#include <mach/i386/thread_status.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/ucontext.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

#define DARWIN_THREAD_FAST_SET_CTHREAD_SELF UINT64_C(0x03000003)
#define HRT_LINUX_GETDENTS64 217
#define HRT_DIRECTORY_NAME_MAX 1024
#define HRT_LINUX_DIRENT64_HEADER_SIZE 19u

typedef struct {
    DIR *stream;
    char host_path[HRT_MAX_PATH];
    uint64_t pending_ino;
    int64_t pending_off;
    uint8_t pending_type;
    char pending_name[HRT_DIRECTORY_NAME_MAX];
    int has_pending;
} HrtDirectoryState;

static volatile sig_atomic_t g_in_handler;
static HrtDirectoryState g_directories[HRT_MAX_TRACKED_FDS];

static inline uintptr_t raw_set_gs(uintptr_t base) {
    uintptr_t previous;
    __asm__ volatile(
        "syscall"
        : "=a"(previous)
        : "0"(DARWIN_THREAD_FAST_SET_CTHREAD_SELF), "D"(base)
        : "rcx", "r11", "cc", "memory");
    return previous;
}

static uint8_t linux_directory_type(uint8_t host_type) {
    switch (host_type) {
#ifdef DT_FIFO
        case DT_FIFO: return 1;
#endif
#ifdef DT_CHR
        case DT_CHR: return 2;
#endif
#ifdef DT_DIR
        case DT_DIR: return 4;
#endif
#ifdef DT_BLK
        case DT_BLK: return 6;
#endif
#ifdef DT_REG
        case DT_REG: return 8;
#endif
#ifdef DT_LNK
        case DT_LNK: return 10;
#endif
#ifdef DT_SOCK
        case DT_SOCK: return 12;
#endif
        default: return 0;
    }
}

static void reset_directory_state(HrtDirectoryState *state) {
    if (state->stream != NULL) {
        (void)closedir(state->stream);
    }
    memset(state, 0, sizeof(*state));
}

static HrtDirectoryState *directory_state_for_fd(int fd) {
    if (fd < 0 || fd >= HRT_MAX_TRACKED_FDS) {
        errno = EBADF;
        return NULL;
    }
    const char *path = lookup_fd_path(fd);
    if (path == NULL) {
        errno = EBADF;
        return NULL;
    }

    HrtDirectoryState *state = &g_directories[fd];
    if (state->stream != NULL && strcmp(state->host_path, path) != 0) {
        reset_directory_state(state);
    }
    if (state->stream == NULL) {
        int duplicate = dup(fd);
        if (duplicate < 0) return NULL;
        DIR *stream = fdopendir(duplicate);
        if (stream == NULL) {
            int saved = errno;
            (void)close(duplicate);
            errno = saved;
            return NULL;
        }
        state->stream = stream;
        size_t length = strlen(path);
        if (length + 1u > sizeof(state->host_path)) {
            reset_directory_state(state);
            errno = ENAMETOOLONG;
            return NULL;
        }
        memcpy(state->host_path, path, length + 1u);
    }
    return state;
}

static int load_pending_directory_entry(HrtDirectoryState *state) {
    if (state->has_pending) return 1;
    errno = 0;
    struct dirent *entry = readdir(state->stream);
    if (entry == NULL) return errno == 0 ? 0 : -1;

    size_t name_length = strlen(entry->d_name);
    if (name_length + 1u > sizeof(state->pending_name)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    state->pending_ino = (uint64_t)entry->d_ino;
    long position = telldir(state->stream);
    state->pending_off = position < 0 ? 0 : (int64_t)position;
    state->pending_type = linux_directory_type(entry->d_type);
    memcpy(state->pending_name, entry->d_name, name_length + 1u);
    state->has_pending = 1;
    return 1;
}

static int64_t linux_getdents64(int fd, void *buffer_pointer,
                                size_t buffer_size) {
    if (buffer_pointer == NULL) return hrt_linux_failure(HRT_LINUX_EFAULT);
    if (buffer_size < 24u) return hrt_linux_failure(HRT_LINUX_EINVAL);

    HrtDirectoryState *state = directory_state_for_fd(fd);
    if (state == NULL) return hrt_linux_failure(hrt_linux_errno(errno));

    unsigned char *buffer = buffer_pointer;
    size_t used = 0;
    while (used < buffer_size) {
        int loaded = load_pending_directory_entry(state);
        if (loaded < 0) {
            return used != 0u ? (int64_t)used
                              : hrt_linux_failure(hrt_linux_errno(errno));
        }
        if (loaded == 0) break;

        size_t name_length = strlen(state->pending_name);
        if (name_length > SIZE_MAX - HRT_LINUX_DIRENT64_HEADER_SIZE - 8u) {
            return used != 0u ? (int64_t)used
                              : hrt_linux_failure(HRT_LINUX_EINVAL);
        }
        size_t record_length =
            (HRT_LINUX_DIRENT64_HEADER_SIZE + name_length + 1u + 7u) &
            ~(size_t)7u;
        if (record_length > UINT16_MAX) {
            return used != 0u ? (int64_t)used
                              : hrt_linux_failure(HRT_LINUX_EINVAL);
        }
        if (record_length > buffer_size - used) {
            if (used == 0u) return hrt_linux_failure(HRT_LINUX_EINVAL);
            break;
        }

        unsigned char *record = buffer + used;
        memset(record, 0, record_length);
        uint16_t short_length = (uint16_t)record_length;
        memcpy(record, &state->pending_ino, sizeof(state->pending_ino));
        memcpy(record + 8u, &state->pending_off,
               sizeof(state->pending_off));
        memcpy(record + 16u, &short_length, sizeof(short_length));
        record[18] = state->pending_type;
        memcpy(record + HRT_LINUX_DIRENT64_HEADER_SIZE,
               state->pending_name, name_length + 1u);
        state->has_pending = 0;
        used += record_length;
    }
    return (int64_t)used;
}

static void sigill_handler(int signo, siginfo_t *info,
                           void *context_pointer) {
    (void)signo;
    (void)info;
    if (g_in_handler) _exit(125);
    g_in_handler = 1;

#if defined(__x86_64__)
    ucontext_t *context = (ucontext_t *)context_pointer;
    x86_thread_state64_t *state = &context->uc_mcontext->__ss;
    uint64_t rip = state->__rip;
    const unsigned char *instruction =
        (const unsigned char *)(uintptr_t)rip;
    if (instruction[0] != 0x0f || instruction[1] != 0x0b) {
        static const char message[] = "hrt-m5: unexpected SIGILL\n";
        (void)write(STDERR_FILENO, message, sizeof(message) - 1u);
        _exit(124);
    }

    int entered_with_guest_gs = g_runtime.guest_gs_active;
    uintptr_t old_guest_gs = g_runtime.guest_gs_base;
    if (entered_with_guest_gs) {
        (void)raw_set_gs(g_runtime.host_gs_base);
    }

    ++g_runtime.syscall_count;
    HrtSyscallControl control;
    memset(&control, 0, sizeof(control));
    int64_t result;
    if (state->__rax == HRT_HOST_CREATE_WINDOW) {
        result = hrt_host_ui_submit_window(
            (const char *)(uintptr_t)state->__rdi,
            (size_t)state->__rsi,
            (uint32_t)state->__rdx,
            (uint32_t)state->__r10);
    } else if (state->__rax == HRT_HOST_VISIBLE_WINDOWS) {
        result = hrt_host_ui_visible_windows();
    } else if (state->__rax == HRT_LINUX_GETDENTS64) {
        result = linux_getdents64(
            (int)state->__rdi,
            (void *)(uintptr_t)state->__rsi,
            (size_t)state->__rdx);
    } else {
        result = hrt_dispatch_linux_syscall(state, &control);
    }
    state->__rax = (uint64_t)result;
    state->__rip = rip + 2u;

    if (control.set_guest_gs) {
        g_runtime.guest_gs_base = control.new_guest_gs;
        g_runtime.guest_gs_active = 1;
        uintptr_t previous = raw_set_gs(control.new_guest_gs);
        if (!entered_with_guest_gs) {
            g_runtime.host_gs_base = previous;
        }
    } else if (entered_with_guest_gs) {
        (void)raw_set_gs(old_guest_gs);
    }
    g_in_handler = 0;
#else
#error "hrt-m5 must be compiled as x86_64 Mach-O"
#endif
}

void install_sigill_handler(void) {
    void *altstack = mmap(NULL, HRT_ALTSTACK_SIZE,
                          PROT_READ | PROT_WRITE,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (altstack == MAP_FAILED) fatal("mmap alternate signal stack");

    stack_t stack;
    memset(&stack, 0, sizeof(stack));
    stack.ss_sp = altstack;
    stack.ss_size = HRT_ALTSTACK_SIZE;
    if (sigaltstack(&stack, NULL) != 0) fatal("sigaltstack");

    struct sigaction action;
    memset(&action, 0, sizeof(action));
    sigemptyset(&action.sa_mask);
    action.sa_sigaction = sigill_handler;
    action.sa_flags = SA_SIGINFO | SA_ONSTACK;
    if (sigaction(SIGILL, &action, NULL) != 0) {
        fatal("sigaction(SIGILL)");
    }
}
