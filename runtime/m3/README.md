# HOffice Runtime M3 — original HWord entry gate

M3 is credited only when the exact `hoffice_11.20.0.1520+h1_amd64.deb`
HWord executable has been loaded with its real `PT_INTERP` and complete
startup dependency closure, and the dynamic loader transfers control to the
unchanged original HWord ELF entry point.

The gate installs a two-byte `UD2` breakpoint **in memory only** at the HWord
entry address. The package file is never modified. When the original loader
reaches that address, the macOS SIGILL bridge writes a deterministic marker
and terminates before Qt or application constructors are credited.

Passing M3 therefore does not imply a window, rendering, input, IME, document
support, or clean shutdown. Those remain later milestones.
