#!/usr/bin/env python3
"""Complete the locale-complete HWord filesystem and wakeup bridge.

Run 31245615859 proved flock, link, chmod and fstatfs.  Run 31245803508 then
proved atomic rename and left eventfd2 as the only unsupported Linux syscall.
This wrapper executes the immutable first filesystem generator from commit
81e56f4e, adds guest-root-confined rename, and applies the compile-safe mature
pipe-backed eventfd2 bridge that cooperates with directory and epoll close
bookkeeping.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

LOCKED_COMMIT = "81e56f4eaaa8a2f68142c8d05856796877412f33"
LOCKED_PATH = "runtime/m10/augment_fs_compat.py"


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def run_locked_generator(source: Path, output: Path) -> None:
    locked_source = subprocess.run(
        ["git", "show", f"{LOCKED_COMMIT}:{LOCKED_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout

    with tempfile.TemporaryDirectory(prefix="hrt-m10-fs-") as temporary:
        module_path = Path(temporary) / "locked_augment_fs_compat.py"
        module_path.write_text(locked_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "hrt_m10_locked_fs_compat", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit("unable to load the locked filesystem generator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        previous_argv = sys.argv
        try:
            sys.argv = [str(module_path), str(source), str(output)]
            module.main()
        finally:
            sys.argv = previous_argv


def add_rename_bridge(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "LINUX_SYS_RENAME" in text:
        raise SystemExit("Linux rename compatibility is already present")

    text = replace_once(
        text,
        "#ifndef LINUX_SYS_LINK\n"
        "#define LINUX_SYS_LINK UINT64_C(86)\n"
        "#endif\n",
        "#ifndef LINUX_SYS_RENAME\n"
        "#define LINUX_SYS_RENAME UINT64_C(82)\n"
        "#endif\n"
        "#ifndef LINUX_SYS_LINK\n"
        "#define LINUX_SYS_LINK UINT64_C(86)\n"
        "#endif\n",
        "Linux rename syscall constant",
    )

    bridge = r'''static int64_t host_rename_bridge(const char *old_guest_path,
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
    int host_result = rename(old_path, new_path);
    int saved_errno = errno;
    restore_guest_context(guest);
    int64_t result = linux_host_result((int64_t)host_result, saved_errno);
    m10_trace_fs("rename", result, old_path, new_path, 0u);
    return result;
}

'''
    text = replace_once(
        text,
        "static int64_t host_link_bridge(const char *old_guest_path,\n",
        bridge + "static int64_t host_link_bridge(const char *old_guest_path,\n",
        "guest-root-confined rename bridge",
    )

    text = replace_once(
        text,
        "        case LINUX_SYS_LINK:\n"
        "            result = host_link_bridge(\n",
        "        case LINUX_SYS_RENAME:\n"
        "            result = host_rename_bridge(\n"
        "                (const char *)(uintptr_t)state->__rdi,\n"
        "                (const char *)(uintptr_t)state->__rsi);\n"
        "            break;\n"
        "        case LINUX_SYS_LINK:\n"
        "            result = host_link_bridge(\n",
        "Linux rename dispatch",
    )

    required = {
        "case LINUX_SYS_RENAME:": 1,
        "host_rename_bridge(": 2,
        'm10_trace_fs("rename"': 1,
        "#define LINUX_SYS_RENAME UINT64_C(82)": 1,
        "case LINUX_SYS_FLOCK:": 1,
        "case LINUX_SYS_FSTATFS:": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"rename marker count mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    path.write_text(text, encoding="utf-8")


def add_mature_eventfd(path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="hrt-m10-eventfd-") as temporary:
        generated = Path(temporary) / "syscall-eventfd.c"
        subprocess.run(
            [
                sys.executable,
                "runtime/m10/augment_eventfd2_mature.py",
                str(path),
                str(generated),
            ],
            check=True,
        )
        path.write_text(generated.read_text(encoding="utf-8"),
                        encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} SOURCE.c OUTPUT.c")
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    run_locked_generator(source, output)
    add_rename_bridge(output)
    add_mature_eventfd(output)


if __name__ == "__main__":
    main()
