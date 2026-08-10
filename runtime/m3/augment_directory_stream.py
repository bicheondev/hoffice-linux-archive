#!/usr/bin/env python3
"""Replace raw getdents conversion with persistent host directory streams.

The M3 bridge normally services Linux getdents64 from Darwin
getdirentries64 records.  Qt repeatedly opens and scans its plugin paths,
and the raw record route has shown run-to-run differences on the
case-sensitive HFS+ image used by the Apple Silicon runner.  This
augmentation keeps an independent macOS DIR stream for each guest file
descriptor, converts every returned entry into a Linux x86-64
dirent64 record, and disposes the stream when the guest closes the fd.

The generator is fail-closed and only accepts the exact bridge shape
produced by augment_directory_syscalls.py.
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
    if "static int64_t host_getdents64_bridge(" not in text:
        raise SystemExit("getdents64 bridge anchor is missing")
    if "static int64_t bridge_prctl(" not in text:
        raise SystemExit("prctl bridge anchor is missing")
    if "static int64_t host_getdents64_stream_bridge(" in text:
        raise SystemExit("directory stream bridge is already present")

    if "#include <dirent.h>\n" not in text:
        text = replace_once(
            text,
            "#include <errno.h>\n",
            "#include <dirent.h>\n#include <errno.h>\n",
            "dirent include",
        )

    start = text.index("static int64_t host_getdents64_bridge(")
    end = text.index("static int64_t bridge_prctl(", start)

    stream_bridge = r'''#define M3_DIRECTORY_STREAM_SLOTS 64u
#define M3_DIRECTORY_NAME_CAPACITY 1024u

struct M3DirectoryStream {
    int guest_fd;
    DIR *directory;
    uint64_t next_offset;
    int pending_valid;
    uint64_t pending_inode;
    uint8_t pending_type;
    uint16_t pending_name_length;
    char pending_name[M3_DIRECTORY_NAME_CAPACITY];
};

static struct M3DirectoryStream
    g_directory_streams[M3_DIRECTORY_STREAM_SLOTS];

static struct M3DirectoryStream *find_directory_stream(int fd) {
    for (size_t index = 0u; index < M3_DIRECTORY_STREAM_SLOTS; ++index) {
        if (g_directory_streams[index].directory != NULL &&
            g_directory_streams[index].guest_fd == fd) {
            return &g_directory_streams[index];
        }
    }
    return NULL;
}

static struct M3DirectoryStream *allocate_directory_stream(int fd,
                                                            int *error_out) {
    struct M3DirectoryStream *existing = find_directory_stream(fd);
    if (existing != NULL) return existing;

    struct M3DirectoryStream *slot = NULL;
    for (size_t index = 0u; index < M3_DIRECTORY_STREAM_SLOTS; ++index) {
        if (g_directory_streams[index].directory == NULL) {
            slot = &g_directory_streams[index];
            break;
        }
    }
    if (slot == NULL) {
        *error_out = EMFILE;
        return NULL;
    }

    char host_path[HRT_MAX_PATH];
    memset(host_path, 0, sizeof(host_path));
    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int path_result = fcntl(fd, F_GETPATH, host_path);
    int saved_errno = errno;
    DIR *directory = NULL;
    if (path_result == 0) {
        errno = 0;
        directory = opendir(host_path);
        saved_errno = errno;
    }
    restore_guest_context(guest);

    if (path_result != 0 || directory == NULL) {
        *error_out = saved_errno != 0 ? saved_errno : EIO;
        return NULL;
    }

    memset(slot, 0, sizeof(*slot));
    slot->guest_fd = fd;
    slot->directory = directory;
    slot->next_offset = 1u;
    return slot;
}

static void forget_directory_stream(int fd) {
    struct M3DirectoryStream *stream = find_directory_stream(fd);
    if (stream == NULL) return;

    uintptr_t guest = switch_to_host_context();
    (void)closedir(stream->directory);
    restore_guest_context(guest);
    memset(stream, 0, sizeof(*stream));
}

static int load_pending_directory_entry(struct M3DirectoryStream *stream,
                                        int *error_out) {
    if (stream->pending_valid != 0) return 1;

    errno = 0;
    struct dirent *entry = readdir(stream->directory);
    if (entry == NULL) {
        *error_out = errno;
        return 0;
    }

    size_t name_length = strnlen(entry->d_name,
                                 M3_DIRECTORY_NAME_CAPACITY - 1u);
    if (name_length >= M3_DIRECTORY_NAME_CAPACITY - 1u) {
        *error_out = ENAMETOOLONG;
        return -1;
    }

    stream->pending_inode = (uint64_t)entry->d_ino;
    stream->pending_type = (uint8_t)entry->d_type;
    stream->pending_name_length = (uint16_t)name_length;
    memcpy(stream->pending_name, entry->d_name, name_length + 1u);
    stream->pending_valid = 1;
    return 1;
}

static int64_t host_getdents64_stream_bridge(int fd, void *guest_buffer,
                                              size_t guest_size) {
    if (guest_buffer == NULL) return -LINUX_EFAULT;
    if (guest_size < 24u) return -LINUX_EINVAL;

    int host_error = 0;
    struct M3DirectoryStream *stream =
        allocate_directory_stream(fd, &host_error);
    if (stream == NULL) {
        return -(int64_t)linux_errno_from_host(host_error);
    }

    unsigned char *output = (unsigned char *)guest_buffer;
    size_t output_cursor = 0u;
    uintptr_t guest = switch_to_host_context();

    for (;;) {
        int entry_status = load_pending_directory_entry(stream, &host_error);
        if (entry_status < 0) {
            restore_guest_context(guest);
            return -(int64_t)linux_errno_from_host(host_error);
        }
        if (entry_status == 0) {
            restore_guest_context(guest);
            if (host_error != 0 && output_cursor == 0u) {
                return -(int64_t)linux_errno_from_host(host_error);
            }
            return (int64_t)output_cursor;
        }

        const size_t name_length = stream->pending_name_length;
        const size_t linux_record_size = align_linux_dirent(
            M3_LINUX_DIRENT_HEADER_SIZE + name_length + 1u);
        if (linux_record_size > UINT16_MAX) {
            restore_guest_context(guest);
            return -LINUX_EIO;
        }
        if (linux_record_size > guest_size - output_cursor) {
            restore_guest_context(guest);
            if (output_cursor == 0u) return -LINUX_EINVAL;
            return (int64_t)output_cursor;
        }

        unsigned char *linux_entry = output + output_cursor;
        memset(linux_entry, 0, linux_record_size);
        store_u64(linux_entry + 0u,
                  stream->pending_inode != 0u
                      ? stream->pending_inode
                      : stream->next_offset);
        store_u64(linux_entry + 8u, stream->next_offset);
        store_u16(linux_entry + 16u, (uint16_t)linux_record_size);
        linux_entry[18u] = linux_dirent_type(stream->pending_type);
        memcpy(linux_entry + M3_LINUX_DIRENT_HEADER_SIZE,
               stream->pending_name, name_length + 1u);

        if (strcmp(stream->pending_name, "libqoffscreen.so") == 0) {
            static const char marker[] =
                "HRT M5: directory stream yielded libqoffscreen.so\n";
            raw_write_literal(marker, sizeof(marker) - 1u);
        }

        stream->pending_valid = 0;
        ++stream->next_offset;
        output_cursor += linux_record_size;
    }
}

static int64_t host_getdents64_bridge(int fd, void *guest_buffer,
                                      size_t guest_size) {
    return host_getdents64_stream_bridge(fd, guest_buffer, guest_size);
}

'''

    text = text[:start] + stream_bridge + text[end:]
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        "static int64_t host_close_bridge(int fd) {\n"
        "    forget_directory_stream(fd);\n",
        "directory stream close hook",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
