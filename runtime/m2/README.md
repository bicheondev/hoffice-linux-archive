# HOffice Runtime M2

M2 is the first real glibc bootstrap gate. It loads an ordinary dynamically
linked Linux x86-64 PIE together with the distribution's real
`ld-linux-x86-64.so.2`, constructs the Linux initial stack, and translates the
startup syscall subset on macOS.

Apple Silicon Rosetta does not expose a usable Linux-style FS base to this
Mach-O process. The verified M2 strategy therefore keeps macOS host TLS in GS,
rewrites guest FS segment prefixes to GS in memory using exact file-offset
sidecars generated from GNU objdump, and switches GS between host and guest
contexts around every trapped Linux syscall.

This milestone is intentionally single-threaded and compatibility-first.
Guest mappings remain writable and executable while the loader is being
brought up; W^X restoration and multithreaded futex/clone semantics are later
gates.
