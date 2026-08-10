#!/usr/bin/env python3
"""Add Darwin directory enumeration and minimal prctl support to M3.

The generated bridge converts Darwin getdirentries64 records into Linux
x86-64 linux_dirent64 records.  The insertion remains fail-closed: every
anchor must occur exactly once, otherwise generation stops.
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

    text = replace_once(
        text,
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n"
        "#define DARWIN_SYS_GETPID UINT64_C(20)\n",
        "#define DARWIN_SYS_CLOSE UINT64_C(6)\n"
        "#define DARWIN_SYS_GETPID UINT64_C(20)\n"
        "#define DARWIN_SYS_GETDIRENTRIES64 UINT64_C(344)\n"
        "\n"
        "#ifndef LINUX_SYS_PRCTL\n"
        "#define LINUX_SYS_PRCTL UINT64_C(157)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_GETDENTS64\n"
        "#define LINUX_SYS_GETDENTS64 UINT64_C(217)\n"
        "#endif\n"
        "#define LINUX_PR_CAPBSET_READ UINT64_C(23)\n",
        "directory and prctl constants",
    )

    raw_four = r'''static inline int64_t raw_bsd_syscall4(uint64_t number,
                                       uint64_t argument1,
                                       uint64_t argument2,
                                       uint64_t argument3,
                                       uint64_t argument4) {
    uint64_t result;
    unsigned char failed;
    __asm__ volatile(
        "movq %[argument4], %%r10\n\t"
        "syscall\n\t"
        "setc %1"
        : "=a"(result), "=qm"(failed)
        : "0"(DARWIN_BSD_SYSCALL(number)),
          "D"(argument1), "S"(argument2), "d"(argument3),
          [argument4] "r"(argument4)
        : "rcx", "r10", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}

'''
    text = replace_once(
        text,
        "static inline uintptr_t raw_set_gs(uintptr_t base) {\n",
        raw_four + "static inline uintptr_t raw_set_gs(uintptr_t base) {\n",
        "four-argument raw BSD syscall bridge",
    )

    directory_bridge = r'''
#define M3_DARWIN_DIRENT_HEADER_SIZE 21u
#define M3_LINUX_DIRENT_HEADER_SIZE 19u
#define M3_HOST_DIRENT_BUFFER_SIZE (64u * 1024u)

static unsigned char g_host_dirent_buffer[M3_HOST_DIRENT_BUFFER_SIZE];

static uint16_t load_u16(const unsigned char *source) {
    uint16_t value;
    memcpy(&value, source, sizeof(value));
    return value;
}

static uint64_t load_u64(const unsigned char *source) {
    uint64_t value;
    memcpy(&value, source, sizeof(value));
    return value;
}

static void store_u16(unsigned char *destination, uint16_t value) {
    memcpy(destination, &value, sizeof(value));
}

static void store_u64(unsigned char *destination, uint64_t value) {
    memcpy(destination, &value, sizeof(value));
}

static size_t align_linux_dirent(size_t value) {
    return (value + 7u) & ~(size_t)7u;
}

static uint8_t linux_dirent_type(uint8_t host_type) {
    switch (host_type) {
        case 1u: return 1u;   /* FIFO */
        case 2u: return 2u;   /* character device */
        case 4u: return 4u;   /* directory */
        case 6u: return 6u;   /* block device */
        case 8u: return 8u;   /* regular file */
        case 10u: return 10u; /* symbolic link */
        case 12u: return 12u; /* socket */
        default: return 0u;
    }
}

static int64_t host_getdents64_bridge(int fd, void *guest_buffer,
                                      size_t guest_size) {
    if (guest_buffer == NULL) return -LINUX_EFAULT;
    if (guest_size < 24u) return -LINUX_EINVAL;

    size_t host_capacity = guest_size;
    if (host_capacity > sizeof(g_host_dirent_buffer)) {
        host_capacity = sizeof(g_host_dirent_buffer);
    }
    /*
     * Darwin records have a 21-byte header and are at least 4-byte aligned;
     * Linux records have a 19-byte header and are 8-byte aligned. Reserving
     * one eighth guarantees that every converted record fits even in the
     * worst 32-byte Linux / 28-byte Darwin expansion case.
     */
    host_capacity = (host_capacity / 8u) * 7u;
    if (host_capacity < 24u) return -LINUX_EINVAL;

    off_t position = 0;
    uintptr_t guest = switch_to_host_context();
    int64_t host_result = raw_bsd_syscall4(
        DARWIN_SYS_GETDIRENTRIES64, (uint64_t)(unsigned int)fd,
        (uint64_t)(uintptr_t)g_host_dirent_buffer,
        (uint64_t)host_capacity, (uint64_t)(uintptr_t)&position);
    restore_guest_context(guest);

    if (host_result < 0) {
        return -(int64_t)linux_errno_from_host((int)-host_result);
    }
    if ((uint64_t)host_result > (uint64_t)host_capacity) {
        return -LINUX_EIO;
    }

    const size_t host_size = (size_t)host_result;
    size_t input_cursor = 0u;
    size_t output_cursor = 0u;
    unsigned char *output = (unsigned char *)guest_buffer;

    while (input_cursor < host_size) {
        const size_t remaining = host_size - input_cursor;
        if (remaining < M3_DARWIN_DIRENT_HEADER_SIZE) {
            return -LINUX_EIO;
        }

        const unsigned char *entry = g_host_dirent_buffer + input_cursor;
        const uint64_t inode = load_u64(entry + 0u);
        const uint64_t seek_offset = load_u64(entry + 8u);
        const uint16_t host_record_size = load_u16(entry + 16u);
        const uint16_t name_length = load_u16(entry + 18u);
        const uint8_t host_type = entry[20u];

        if (host_record_size < M3_DARWIN_DIRENT_HEADER_SIZE + 1u ||
            (size_t)host_record_size > remaining ||
            (size_t)name_length + M3_DARWIN_DIRENT_HEADER_SIZE >=
                (size_t)host_record_size) {
            return -LINUX_EIO;
        }

        const size_t linux_record_size = align_linux_dirent(
            M3_LINUX_DIRENT_HEADER_SIZE + (size_t)name_length + 1u);
        if (linux_record_size > UINT16_MAX ||
            linux_record_size > guest_size - output_cursor) {
            return -LINUX_EIO;
        }

        unsigned char *linux_entry = output + output_cursor;
        memset(linux_entry, 0, linux_record_size);
        store_u64(linux_entry + 0u, inode);
        store_u64(linux_entry + 8u,
                  seek_offset != 0u ? seek_offset : (uint64_t)position);
        store_u16(linux_entry + 16u, (uint16_t)linux_record_size);
        linux_entry[18u] = linux_dirent_type(host_type);
        memcpy(linux_entry + M3_LINUX_DIRENT_HEADER_SIZE,
               entry + M3_DARWIN_DIRENT_HEADER_SIZE,
               (size_t)name_length);
        linux_entry[M3_LINUX_DIRENT_HEADER_SIZE + name_length] = '\0';

        input_cursor += host_record_size;
        output_cursor += linux_record_size;
    }

    return (int64_t)output_cursor;
}

static int64_t bridge_prctl(uint64_t option) {
    if (option == LINUX_PR_CAPBSET_READ) {
        /* Present an empty capability bounding set to unprivileged guests. */
        return 0;
    }
    return -LINUX_EINVAL;
}

'''
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        directory_bridge + "static int64_t host_close_bridge(int fd) {\n",
        "getdents64 and prctl bridges",
    )

    text = replace_once(
        text,
        "        case LINUX_SYS_ARCH_PRCTL:\n",
        "        case LINUX_SYS_PRCTL:\n"
        "            result = bridge_prctl(state->__rdi);\n"
        "            break;\n"
        "        case LINUX_SYS_ARCH_PRCTL:\n",
        "prctl dispatch",
    )

    text = replace_once(
        text,
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "        case LINUX_SYS_GETDENTS64:\n"
        "            result = host_getdents64_bridge(\n"
        "                (int)state->__rdi,\n"
        "                (void *)(uintptr_t)state->__rsi,\n"
        "                (size_t)state->__rdx);\n"
        "            break;\n"
        "        case LINUX_SYS_SET_TID_ADDRESS:\n",
        "getdents64 dispatch",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
