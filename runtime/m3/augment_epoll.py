#!/usr/bin/env python3
"""Inject a bounded Linux epoll emulation backed by Darwin kqueue.

The implementation is intentionally scoped to the single-process M3/M5
runtime: epoll descriptors are real kqueue file descriptors, watch metadata
lives in fixed host tables, and the core read/write/edge/one-shot semantics
used by GLib are translated.  Unsupported signal-mask variants fail closed.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def add_include(text: str) -> str:
    if "#include <sys/event.h>\n" in text:
        return text
    for anchor in ("#include <poll.h>\n", "#include <signal.h>\n",
                   "#include <sys/mman.h>\n"):
        if anchor in text:
            return text.replace(anchor, anchor + "#include <sys/event.h>\n", 1)
    raise SystemExit("epoll include: no stable system-header anchor")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8")
    if "host_epoll_create1_bridge(" in text:
        raise SystemExit("epoll bridge is already present")
    text = add_include(text)

    text = replace_once(
        text,
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n",
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n"
        "#ifndef LINUX_SYS_EPOLL_CREATE\n"
        "#define LINUX_SYS_EPOLL_CREATE UINT64_C(213)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_EPOLL_WAIT\n"
        "#define LINUX_SYS_EPOLL_WAIT UINT64_C(232)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_EPOLL_CTL\n"
        "#define LINUX_SYS_EPOLL_CTL UINT64_C(233)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_EPOLL_PWAIT\n"
        "#define LINUX_SYS_EPOLL_PWAIT UINT64_C(281)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_EPOLL_CREATE1\n"
        "#define LINUX_SYS_EPOLL_CREATE1 UINT64_C(291)\n"
        "#endif\n"
        "#define LINUX_EPOLL_CLOEXEC UINT32_C(0x80000)\n"
        "#define LINUX_EPOLL_CTL_ADD 1\n"
        "#define LINUX_EPOLL_CTL_DEL 2\n"
        "#define LINUX_EPOLL_CTL_MOD 3\n"
        "#define LINUX_EPOLLIN UINT32_C(0x00000001)\n"
        "#define LINUX_EPOLLPRI UINT32_C(0x00000002)\n"
        "#define LINUX_EPOLLOUT UINT32_C(0x00000004)\n"
        "#define LINUX_EPOLLERR UINT32_C(0x00000008)\n"
        "#define LINUX_EPOLLHUP UINT32_C(0x00000010)\n"
        "#define LINUX_EPOLLRDHUP UINT32_C(0x00002000)\n"
        "#define LINUX_EPOLLONESHOT UINT32_C(0x40000000)\n"
        "#define LINUX_EPOLLET UINT32_C(0x80000000)\n",
        "epoll constants",
    )

    bridge = r'''
#define M3_EPOLL_INSTANCE_CAPACITY 32u
#define M3_EPOLL_WATCH_CAPACITY 1024u
#define M3_EPOLL_RESULT_CAPACITY 256u
#define M3_LINUX_EPOLL_EVENT_SIZE 12u

struct M3EpollInstance {
    int used;
    int epoll_fd;
};

struct M3EpollWatch {
    int used;
    int epoll_fd;
    int target_fd;
    uint32_t events;
    uint64_t data;
};

static struct M3EpollInstance
    g_epoll_instances[M3_EPOLL_INSTANCE_CAPACITY];
static struct M3EpollWatch g_epoll_watches[M3_EPOLL_WATCH_CAPACITY];
static struct kevent g_epoll_host_events[M3_EPOLL_RESULT_CAPACITY];

static uint32_t m3_epoll_load_u32(const unsigned char *source) {
    uint32_t value;
    memcpy(&value, source, sizeof(value));
    return value;
}

static uint64_t m3_epoll_load_u64(const unsigned char *source) {
    uint64_t value;
    memcpy(&value, source, sizeof(value));
    return value;
}

static void m3_epoll_store_u32(unsigned char *destination, uint32_t value) {
    memcpy(destination, &value, sizeof(value));
}

static void m3_epoll_store_u64(unsigned char *destination, uint64_t value) {
    memcpy(destination, &value, sizeof(value));
}

static struct M3EpollInstance *find_epoll_instance(int epoll_fd) {
    for (size_t index = 0u; index < M3_EPOLL_INSTANCE_CAPACITY; ++index) {
        if (g_epoll_instances[index].used != 0 &&
            g_epoll_instances[index].epoll_fd == epoll_fd) {
            return &g_epoll_instances[index];
        }
    }
    return NULL;
}

static struct M3EpollWatch *find_epoll_watch(int epoll_fd, int target_fd) {
    for (size_t index = 0u; index < M3_EPOLL_WATCH_CAPACITY; ++index) {
        if (g_epoll_watches[index].used != 0 &&
            g_epoll_watches[index].epoll_fd == epoll_fd &&
            g_epoll_watches[index].target_fd == target_fd) {
            return &g_epoll_watches[index];
        }
    }
    return NULL;
}

static struct M3EpollWatch *allocate_epoll_watch(void) {
    for (size_t index = 0u; index < M3_EPOLL_WATCH_CAPACITY; ++index) {
        if (g_epoll_watches[index].used == 0) {
            memset(&g_epoll_watches[index], 0,
                   sizeof(g_epoll_watches[index]));
            g_epoll_watches[index].used = 1;
            return &g_epoll_watches[index];
        }
    }
    return NULL;
}

static int apply_epoll_filter(int epoll_fd, int target_fd,
                              int16_t filter, uint16_t flags,
                              struct M3EpollWatch *watch,
                              int ignore_missing) {
    struct kevent change;
    EV_SET(&change, (uintptr_t)(unsigned int)target_fd,
           filter, flags, 0u, 0, watch);
    errno = 0;
    int result = kevent(epoll_fd, &change, 1, NULL, 0, NULL);
    if (result == 0) return 0;
    if (ignore_missing != 0 && errno == ENOENT) return 0;
    return -1;
}

static int remove_epoll_watch_filters(struct M3EpollWatch *watch) {
    int result = 0;
    if ((watch->events & (LINUX_EPOLLIN | LINUX_EPOLLPRI)) != 0u) {
        if (apply_epoll_filter(watch->epoll_fd, watch->target_fd,
                               EVFILT_READ, EV_DELETE, watch, 1) != 0) {
            result = -1;
        }
    }
    if ((watch->events & LINUX_EPOLLOUT) != 0u) {
        if (apply_epoll_filter(watch->epoll_fd, watch->target_fd,
                               EVFILT_WRITE, EV_DELETE, watch, 1) != 0) {
            result = -1;
        }
    }
    return result;
}

static int add_epoll_watch_filters(struct M3EpollWatch *watch) {
    uint16_t flags = EV_ADD | EV_ENABLE;
    if ((watch->events & LINUX_EPOLLET) != 0u) flags |= EV_CLEAR;
    if ((watch->events & LINUX_EPOLLONESHOT) != 0u) flags |= EV_ONESHOT;

    if ((watch->events & (LINUX_EPOLLIN | LINUX_EPOLLPRI)) != 0u) {
        if (apply_epoll_filter(watch->epoll_fd, watch->target_fd,
                               EVFILT_READ, flags, watch, 0) != 0) {
            return -1;
        }
    }
    if ((watch->events & LINUX_EPOLLOUT) != 0u) {
        if (apply_epoll_filter(watch->epoll_fd, watch->target_fd,
                               EVFILT_WRITE, flags, watch, 0) != 0) {
            (void)apply_epoll_filter(watch->epoll_fd, watch->target_fd,
                                     EVFILT_READ, EV_DELETE, watch, 1);
            return -1;
        }
    }
    return 0;
}

static int64_t host_epoll_create1_bridge(uint64_t linux_flags) {
    if ((linux_flags & ~(uint64_t)LINUX_EPOLL_CLOEXEC) != 0u) {
        return -LINUX_EINVAL;
    }

    struct M3EpollInstance *slot = NULL;
    for (size_t index = 0u; index < M3_EPOLL_INSTANCE_CAPACITY; ++index) {
        if (g_epoll_instances[index].used == 0) {
            slot = &g_epoll_instances[index];
            break;
        }
    }
    if (slot == NULL) return -LINUX_EMFILE;

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int descriptor = kqueue();
    int saved_errno = errno;
    if (descriptor >= 0 &&
        (linux_flags & LINUX_EPOLL_CLOEXEC) != 0u &&
        fcntl(descriptor, F_SETFD, FD_CLOEXEC) != 0) {
        saved_errno = errno;
        (void)close(descriptor);
        descriptor = -1;
    }
    restore_guest_context(guest);
    if (descriptor < 0) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }

    slot->used = 1;
    slot->epoll_fd = descriptor;
    return descriptor;
}

static int64_t host_epoll_create_bridge(int size_hint) {
    if (size_hint <= 0) return -LINUX_EINVAL;
    return host_epoll_create1_bridge(0u);
}

static int64_t host_epoll_ctl_bridge(int epoll_fd, int operation,
                                     int target_fd,
                                     const unsigned char *linux_event) {
    if (find_epoll_instance(epoll_fd) == NULL) return -LINUX_EBADF;
    if (target_fd == epoll_fd) return -LINUX_EINVAL;

    struct M3EpollWatch *watch = find_epoll_watch(epoll_fd, target_fd);
    if (operation == LINUX_EPOLL_CTL_ADD && watch != NULL) {
        return -LINUX_EEXIST;
    }
    if ((operation == LINUX_EPOLL_CTL_DEL ||
         operation == LINUX_EPOLL_CTL_MOD) && watch == NULL) {
        return -LINUX_ENOENT;
    }
    if (operation != LINUX_EPOLL_CTL_ADD &&
        operation != LINUX_EPOLL_CTL_DEL &&
        operation != LINUX_EPOLL_CTL_MOD) {
        return -LINUX_EINVAL;
    }
    if (operation != LINUX_EPOLL_CTL_DEL && linux_event == NULL) {
        return -LINUX_EFAULT;
    }

    uint32_t new_events = 0u;
    uint64_t new_data = 0u;
    if (operation != LINUX_EPOLL_CTL_DEL) {
        new_events = m3_epoll_load_u32(linux_event + 0u);
        new_data = m3_epoll_load_u64(linux_event + 4u);
    }

    uintptr_t guest = switch_to_host_context();
    int saved_errno = 0;
    if (operation == LINUX_EPOLL_CTL_ADD) {
        watch = allocate_epoll_watch();
        if (watch == NULL) {
            restore_guest_context(guest);
            return -LINUX_ENOMEM;
        }
        watch->epoll_fd = epoll_fd;
        watch->target_fd = target_fd;
        watch->events = new_events;
        watch->data = new_data;
        if (add_epoll_watch_filters(watch) != 0) {
            saved_errno = errno;
            memset(watch, 0, sizeof(*watch));
        }
    } else if (operation == LINUX_EPOLL_CTL_MOD) {
        uint32_t old_events = watch->events;
        uint64_t old_data = watch->data;
        if (remove_epoll_watch_filters(watch) != 0) {
            saved_errno = errno;
        } else {
            watch->events = new_events;
            watch->data = new_data;
            if (add_epoll_watch_filters(watch) != 0) {
                saved_errno = errno;
                watch->events = old_events;
                watch->data = old_data;
                (void)add_epoll_watch_filters(watch);
            }
        }
    } else {
        if (remove_epoll_watch_filters(watch) != 0) {
            saved_errno = errno;
        } else {
            memset(watch, 0, sizeof(*watch));
        }
    }
    restore_guest_context(guest);
    if (saved_errno != 0) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }
    return 0;
}

static uint32_t linux_events_from_kevent(const struct kevent *event) {
    uint32_t result = 0u;
    if (event->filter == EVFILT_READ) result |= LINUX_EPOLLIN;
    if (event->filter == EVFILT_WRITE) result |= LINUX_EPOLLOUT;
    if ((event->flags & EV_EOF) != 0u) {
        result |= LINUX_EPOLLHUP | LINUX_EPOLLRDHUP;
    }
    if ((event->flags & EV_ERROR) != 0u) result |= LINUX_EPOLLERR;
    return result;
}

static int64_t host_epoll_wait_bridge(int epoll_fd,
                                      unsigned char *linux_events,
                                      int maximum_events,
                                      int timeout_milliseconds,
                                      const void *linux_signal_mask) {
    if (find_epoll_instance(epoll_fd) == NULL) return -LINUX_EBADF;
    if (linux_events == NULL) return -LINUX_EFAULT;
    if (maximum_events <= 0) return -LINUX_EINVAL;
    if (linux_signal_mask != NULL) return -LINUX_EINVAL;

    int capacity = maximum_events;
    if (capacity > (int)M3_EPOLL_RESULT_CAPACITY) {
        capacity = (int)M3_EPOLL_RESULT_CAPACITY;
    }
    struct timespec timeout;
    struct timespec *timeout_pointer = NULL;
    if (timeout_milliseconds >= 0) {
        timeout.tv_sec = timeout_milliseconds / 1000;
        timeout.tv_nsec =
            (long)(timeout_milliseconds % 1000) * 1000000L;
        timeout_pointer = &timeout;
    }

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int result = kevent(epoll_fd, NULL, 0, g_epoll_host_events,
                        capacity, timeout_pointer);
    int saved_errno = errno;
    restore_guest_context(guest);
    if (result < 0) {
        return -(int64_t)linux_errno_from_host(saved_errno);
    }

    int output_count = 0;
    for (int index = 0; index < result && output_count < maximum_events;
         ++index) {
        struct M3EpollWatch *watch =
            (struct M3EpollWatch *)g_epoll_host_events[index].udata;
        if (watch == NULL || watch->used == 0 ||
            watch->epoll_fd != epoll_fd) {
            continue;
        }

        uint32_t events = linux_events_from_kevent(
            &g_epoll_host_events[index]);
        int existing = -1;
        for (int output = 0; output < output_count; ++output) {
            unsigned char *record = linux_events +
                (size_t)output * M3_LINUX_EPOLL_EVENT_SIZE;
            if (m3_epoll_load_u64(record + 4u) == watch->data) {
                existing = output;
                break;
            }
        }
        if (existing >= 0) {
            unsigned char *record = linux_events +
                (size_t)existing * M3_LINUX_EPOLL_EVENT_SIZE;
            events |= m3_epoll_load_u32(record + 0u);
            m3_epoll_store_u32(record + 0u, events);
            continue;
        }

        unsigned char *record = linux_events +
            (size_t)output_count * M3_LINUX_EPOLL_EVENT_SIZE;
        m3_epoll_store_u32(record + 0u, events);
        m3_epoll_store_u64(record + 4u, watch->data);
        ++output_count;
    }
    return output_count;
}

static void forget_epoll_state(int descriptor) {
    for (size_t index = 0u; index < M3_EPOLL_WATCH_CAPACITY; ++index) {
        if (g_epoll_watches[index].used != 0 &&
            (g_epoll_watches[index].epoll_fd == descriptor ||
             g_epoll_watches[index].target_fd == descriptor)) {
            memset(&g_epoll_watches[index], 0,
                   sizeof(g_epoll_watches[index]));
        }
    }
    struct M3EpollInstance *instance = find_epoll_instance(descriptor);
    if (instance != NULL) memset(instance, 0, sizeof(*instance));
}

'''
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        bridge + "static int64_t host_close_bridge(int fd) {\n"
        "    forget_epoll_state(fd);\n",
        "epoll bridge and close hook",
    )

    dispatch = (
        "        case LINUX_SYS_EPOLL_CREATE:\n"
        "            result = host_epoll_create_bridge((int)state->__rdi);\n"
        "            break;\n"
        "        case LINUX_SYS_EPOLL_CREATE1:\n"
        "            result = host_epoll_create1_bridge(state->__rdi);\n"
        "            break;\n"
        "        case LINUX_SYS_EPOLL_CTL:\n"
        "            result = host_epoll_ctl_bridge(\n"
        "                (int)state->__rdi, (int)state->__rsi,\n"
        "                (int)state->__rdx,\n"
        "                (const unsigned char *)(uintptr_t)state->__r10);\n"
        "            break;\n"
        "        case LINUX_SYS_EPOLL_WAIT:\n"
        "            result = host_epoll_wait_bridge(\n"
        "                (int)state->__rdi,\n"
        "                (unsigned char *)(uintptr_t)state->__rsi,\n"
        "                (int)state->__rdx, (int)state->__r10, NULL);\n"
        "            break;\n"
        "        case LINUX_SYS_EPOLL_PWAIT:\n"
        "            result = host_epoll_wait_bridge(\n"
        "                (int)state->__rdi,\n"
        "                (unsigned char *)(uintptr_t)state->__rsi,\n"
        "                (int)state->__rdx, (int)state->__r10,\n"
        "                (const void *)(uintptr_t)state->__r8);\n"
        "            break;\n"
    )
    text = replace_once(
        text,
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        dispatch + "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "epoll dispatch",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
