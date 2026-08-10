# HRT M2 — real `ld-linux` and glibc bootstrap

M2 replaces the synthetic M1 interpreter with an unmodified Linux
`ld-linux-x86-64.so.2` and a dynamically linked glibc test program.

The host remains an x86-64 Mach-O process running through Rosetta on Apple
Silicon. It maps the Linux main executable and loader itself, then translates
Linux syscalls from patched `syscall` instructions into macOS operations.

## Initial compatibility surface

- Sysroot-aware `open`, `openat`, `access`, `stat`, `lstat`, `fstat`,
  `newfstatat`, `readlink`, and `readlinkat`
- `read`, `write`, `readv`, `writev`, `pread64`, `lseek`, `close`, and `fcntl`
- Linux `mmap`, `mprotect`, `munmap`, `brk`, and executable-page syscall patching
- `arch_prctl(ARCH_SET_FS/ARCH_GET_FS)` through x86 FSGSBASE instructions
- Initial process, identity, random, clock, limit, affinity, futex, robust-list,
  signal-mask, and rseq fallbacks needed during glibc startup
- Linux-to-macOS errno and `struct stat` translation

Unsupported calls are logged and return Linux `ENOSYS`; the bridge stops after
an excessive unsupported-call loop rather than silently claiming success.

## Acceptance output

```text
HRT M2: real ld-linux and glibc reached the dynamic main program
```

M2 is not yet an HOffice milestone. Passing it establishes the loader/libc
substrate needed before attempting the packaged Qt and HOffice executables.
