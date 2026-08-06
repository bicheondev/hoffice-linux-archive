# HOffice Runtime M0

This is a clean-room foundation for running the Linux x86-64 HOffice binaries on macOS without a VM or remote desktop.

M0 deliberately targets a tiny static Linux x86-64 ELF. The macOS host executable is itself x86-64 Mach-O, so Apple Silicon runs it through Rosetta. The loader maps Linux `PT_LOAD` segments, constructs a Linux process-entry stack, rewrites guest `syscall` instructions to `ud2`, catches `SIGILL`, and translates a minimal Linux syscall set (`write`, `getpid`, `exit`, and `exit_group`) to Darwin.

Passing M0 proves all of the following in CI:

1. An x86-64 Mach-O compatibility host runs on the Apple Silicon runner.
2. Raw executable pages originating from an ELF image can execute inside that host.
3. Linux syscall instructions can be trapped before Darwin interprets them.
4. Register state can be read and updated through the macOS x86-64 signal context.

M0 is not yet an HOffice-capable runtime. The next gates are:

- M1: dynamic ELF interpreter loading and Linux auxiliary-vector completeness.
- M2: memory, file, time, signal, TLS, and thread syscall coverage sufficient for glibc.
- M3: launch an unchanged packaged HOffice binary through its bundled loader and libraries.
- M4: local graphics transport using the packaged Qt ABI.
- M5: persistent AppKit window, rendering, input, clipboard, and Korean IME.
- M6: Hwp, Hword, HCell, and HShow app integration and document lifecycle.
