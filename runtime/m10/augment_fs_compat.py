#!/usr/bin/env python3
"""Add the filesystem syscalls exercised by locale-complete exact HWord.

The first locale/resource-complete M9 run reached a rendered ``Exception``
dialog only after repeatedly receiving ENOSYS for Linux x86-64 ``flock`` and
also probing ``link``, ``chmod`` and ``fstatfs``.  This fail-closed transform
implements exactly those four calls on Darwin:

* ``flock(2)`` preserves Linux LOCK_SH/EX/NB/UN semantics;
* ``link(2)`` and ``chmod(2)`` keep both paths confined to the guest root; and
* ``fstatfs(2)`` translates Darwin's statfs record to the 120-byte Linux
  x86-64 ABI while presenting the APFS/HFS backing image as a stable local
  filesystem.

Every insertion anchor must match exactly once.  The transform intentionally
does not claim a general Linux VFS emulation layer.
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
    if "HRT M10 FS:" in text:
        raise SystemExit("M10 filesystem compatibility is already present")

    text = replace_once(
        text,
        "#include <sys/mman.h>\n#include <sys/socket.h>\n",
        "#include <sys/mman.h>\n"
        "#include <sys/socket.h>\n"
        "#include <sys/file.h>\n"
        "#include <sys/mount.h>\n",
        "Darwin filesystem headers",
    )

    syscall_anchor = (
        "#ifndef LINUX_SYS_SOCKET\n"
        "#define LINUX_SYS_SOCKET UINT64_C(41)\n"
        "#endif\n"
    )
    syscall_replacement = syscall_anchor + (
        "#ifndef LINUX_SYS_FLOCK\n"
        "#define LINUX_SYS_FLOCK UINT64_C(73)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_LINK\n"
        "#define LINUX_SYS_LINK UINT64_C(86)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_CHMOD\n"
        "#define LINUX_SYS_CHMOD UINT64_C(90)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_FSTATFS\n"
        "#define LINUX_SYS_FSTATFS UINT64_C(138)\n"
        "#endif\n"
        "#define LINUX_ST_RDONLY UINT64_C(1)\n"
        "#define LINUX_ST_NOSUID UINT64_C(2)\n"
        "#define LINUX_LOCAL_FS_MAGIC INT64_C(0xef53)\n"
    )
    text = replace_once(
        text, syscall_anchor, syscall_replacement,
        "Linux filesystem syscall constants",
    )

    struct_anchor = "static int translate_open_flags(uint64_t linux_flags) {\n"
    struct_definition = r'''typedef struct {
    int64_t f_type;
    int64_t f_bsize;
    uint64_t f_blocks;
    uint64_t f_bfree;
    uint64_t f_bavail;
    uint64_t f_files;
    uint64_t f_ffree;
    int32_t f_fsid[2];
    int64_t f_namelen;
    int64_t f_frsize;
    int64_t f_flags;
    int64_t f_spare[4];
} LinuxStatfs;

_Static_assert(sizeof(LinuxStatfs) == 120u,
               "Linux x86-64 statfs ABI must remain 120 bytes");

static int translate_open_flags(uint64_t linux_flags) {
'''
    text = replace_once(
        text, struct_anchor, struct_definition,
        "Linux statfs ABI definition",
    )

    bridges = r'''
#define M10_FS_TRACE_LIMIT 256u

static unsigned int g_m10_fs_trace_count;

static void m10_trace_fs(const char *operation, int64_t result,
                         const char *first_path, const char *second_path,
                         uint64_t argument) {
    if (g_m10_fs_trace_count >= M10_FS_TRACE_LIMIT) return;
    ++g_m10_fs_trace_count;

    char buffer[PATH_MAX * 2 + 320];
    size_t cursor = 0u;
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer),
                                  "HRT M10 FS: op=");
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), operation);
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " result=");
    if (result < 0) {
        if (cursor < sizeof(buffer)) buffer[cursor++] = '-';
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)(-result));
    } else {
        cursor = trace_append_decimal(buffer, cursor, sizeof(buffer),
                                      (uint64_t)result);
    }
    cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " arg=");
    cursor = trace_append_hex(buffer, cursor, sizeof(buffer), argument);
    if (first_path != NULL) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " path1=");
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer), first_path);
    }
    if (second_path != NULL) {
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer), " path2=");
        cursor = trace_append_literal(buffer, cursor, sizeof(buffer), second_path);
    }
    if (cursor < sizeof(buffer)) buffer[cursor++] = '\n';
    size_t written = cursor < sizeof(buffer) ? cursor : sizeof(buffer);
    raw_write_literal(buffer, written);
}

static int64_t host_flock_bridge(int fd, uint64_t linux_operation) {
    const uint64_t known = UINT64_C(1) | UINT64_C(2) |
                           UINT64_C(4) | UINT64_C(8);
    const uint64_t base = linux_operation &
        (UINT64_C(1) | UINT64_C(2) | UINT64_C(8));
    if ((linux_operation & ~known) != 0u ||
        (base != UINT64_C(1) && base != UINT64_C(2) &&
         base != UINT64_C(8))) {
        m10_trace_fs("flock-reject", -LINUX_EINVAL, NULL, NULL,
                     linux_operation);
        return -LINUX_EINVAL;
    }

    int host_operation = 0;
    if ((linux_operation & UINT64_C(1)) != 0u) host_operation |= LOCK_SH;
    if ((linux_operation & UINT64_C(2)) != 0u) host_operation |= LOCK_EX;
    if ((linux_operation & UINT64_C(4)) != 0u) host_operation |= LOCK_NB;
    if ((linux_operation & UINT64_C(8)) != 0u) host_operation |= LOCK_UN;

    uintptr_t guest = switch_to_host_context();
    errno = 0;
    int host_result = flock(fd, host_operation);
    int saved_errno = errno;
    restore_guest_context(guest);
    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    m10_trace_fs("flock", result, NULL, NULL, linux_operation);
    return result;
}

static int64_t host_link_bridge(const char *old_guest_path,
                                const char *new_guest_path) {
    if (old_guest_path == NULL || new_guest_path == NULL)
        return -LINUX_EFAULT;

    uintptr_t guest = switch_to_host_context();
    char old_path[PATH_MAX];
    char new_path[PATH_MAX];
    if (translate_guest_path(old_guest_path, old_path, sizeof(old_path)) != 0 ||
        translate_guest_path(new_guest_path, new_path, sizeof(new_path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    errno = 0;
    int host_result = link(old_path, new_path);
    int saved_errno = errno;
    restore_guest_context(guest);
    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    m10_trace_fs("link", result, old_path, new_path, 0u);
    return result;
}

static int64_t host_chmod_bridge(const char *guest_path, uint64_t mode) {
    if (guest_path == NULL) return -LINUX_EFAULT;

    uintptr_t guest = switch_to_host_context();
    char path[PATH_MAX];
    if (translate_guest_path(guest_path, path, sizeof(path)) != 0) {
        restore_guest_context(guest);
        return -LINUX_ENAMETOOLONG;
    }
    errno = 0;
    int host_result = chmod(path, (mode_t)(mode & UINT64_C(07777)));
    int saved_errno = errno;
    restore_guest_context(guest);
    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    m10_trace_fs("chmod", result, path, NULL, mode);
    return result;
}

static void linux_statfs_from_host(LinuxStatfs *guest,
                                   const struct statfs *host) {
    memset(guest, 0, sizeof(*guest));
    guest->f_type = LINUX_LOCAL_FS_MAGIC;
    guest->f_bsize = (int64_t)host->f_bsize;
    guest->f_blocks = host->f_blocks;
    guest->f_bfree = host->f_bfree;
    guest->f_bavail = host->f_bavail;
    guest->f_files = host->f_files;
    guest->f_ffree = host->f_ffree;
    guest->f_fsid[0] = host->f_fsid.val[0];
    guest->f_fsid[1] = host->f_fsid.val[1];
    guest->f_namelen = INT64_C(255);
    guest->f_frsize = (int64_t)host->f_bsize;
    if ((host->f_flags & MNT_RDONLY) != 0u)
        guest->f_flags |= (int64_t)LINUX_ST_RDONLY;
    if ((host->f_flags & MNT_NOSUID) != 0u)
        guest->f_flags |= (int64_t)LINUX_ST_NOSUID;
}

static int64_t host_fstatfs_bridge(int fd, LinuxStatfs *guest_statfs) {
    if (guest_statfs == NULL) return -LINUX_EFAULT;

    uintptr_t guest = switch_to_host_context();
    struct statfs host_statfs;
    memset(&host_statfs, 0, sizeof(host_statfs));
    errno = 0;
    int host_result = fstatfs(fd, &host_statfs);
    int saved_errno = errno;
    if (host_result == 0)
        linux_statfs_from_host(guest_statfs, &host_statfs);
    restore_guest_context(guest);
    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    m10_trace_fs("fstatfs", result, NULL, NULL, (uint64_t)(unsigned int)fd);
    return result;
}

'''
    text = replace_once(
        text,
        "static int64_t host_close_bridge(int fd) {\n",
        bridges + "static int64_t host_close_bridge(int fd) {\n",
        "filesystem compatibility bridges",
    )

    dispatch_anchor = '''        case LINUX_SYS_TIME:
            result = bridge_time((int64_t *)(uintptr_t)state->__rdi);
            break;
        case LINUX_SYS_MADVISE:
'''
    dispatch_replacement = '''        case LINUX_SYS_TIME:
            result = bridge_time((int64_t *)(uintptr_t)state->__rdi);
            break;
        case LINUX_SYS_FLOCK:
            result = host_flock_bridge((int)state->__rdi, state->__rsi);
            break;
        case LINUX_SYS_LINK:
            result = host_link_bridge(
                (const char *)(uintptr_t)state->__rdi,
                (const char *)(uintptr_t)state->__rsi);
            break;
        case LINUX_SYS_CHMOD:
            result = host_chmod_bridge(
                (const char *)(uintptr_t)state->__rdi, state->__rsi);
            break;
        case LINUX_SYS_FSTATFS:
            result = host_fstatfs_bridge(
                (int)state->__rdi,
                (LinuxStatfs *)(uintptr_t)state->__rsi);
            break;
        case LINUX_SYS_MADVISE:
'''
    text = replace_once(
        text, dispatch_anchor, dispatch_replacement,
        "filesystem syscall dispatch",
    )

    required = {
        "case LINUX_SYS_FLOCK:": 1,
        "case LINUX_SYS_LINK:": 1,
        "case LINUX_SYS_CHMOD:": 1,
        "case LINUX_SYS_FSTATFS:": 1,
        "host_flock_bridge(": 2,
        "host_link_bridge(": 2,
        "host_chmod_bridge(": 2,
        "host_fstatfs_bridge(": 2,
        "HRT M10 FS:": 1,
        "sizeof(LinuxStatfs) == 120u": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"filesystem marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
