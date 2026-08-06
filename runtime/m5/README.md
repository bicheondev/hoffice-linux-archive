# HOffice Runtime M5A — AppKit host-call bridge

M5A moves the Linux guest onto a dedicated Rosetta x86-64 thread while the
Mach-O main thread owns the macOS AppKit run loop. A reserved clean-room host
call is transported through the existing Linux syscall trap bridge. The
signal handler writes a fixed-size request to a datagram socket; the AppKit
main queue creates and retains a native `NSWindow`.

The first proof uses a tiny `LD_PRELOAD` guest constructor and a normal glibc
PIE. It verifies all of the following on Apple Silicon CI:

- Linux guest constructor execution under the real dynamic loader;
- guest-to-host request transport without calling AppKit from a signal handler;
- AppKit ownership by the Mach-O main thread;
- a visible native `NSWindow`, marker JSON, and captured PNG;
- guest observation of the visible-window count before clean exit.

M5A is not yet a Qt QPA implementation and does not render HWord pixels. It is
the host window/IPC foundation on which the exact Qt 5.11.3 QPA adapter will
be built.
