# HRT M1 — PT_INTERP handoff

M1 extends the clean-room M0 Linux ELF execution core with the process-start
semantics needed by a dynamically interpreted Linux executable.

## Implemented in this milestone

- Parse an absolute `PT_INTERP` path from the main ELF.
- Resolve both the main program and interpreter inside an explicit sysroot.
- Map two independent x86-64 ELF images with separate load biases.
- Patch Linux `syscall` instructions in both executable images.
- Construct the Linux initial stack for the interpreter.
- Supply main-program metadata through `AT_PHDR`, `AT_PHENT`, `AT_PHNUM`,
  `AT_ENTRY`, and interpreter load bias through `AT_BASE`.
- Enter the interpreter first and let it transfer control to the main entry.

The CI test deliberately uses a tiny synthetic Linux interpreter. It validates
kernel-to-loader ABI handoff without pretending that glibc or HOffice can run
at this stage.

## Acceptance output

```text
HRT M1: PT_INTERP received AT_BASE and transferred control
HRT M1: main program reached through synthetic Linux interpreter
```

## Not yet implemented

- ELF dynamic relocation processing by a real `ld-linux-x86-64.so.2`
- Linux file-descriptor and virtual-filesystem translation
- `mmap`, TLS, `arch_prctl`, threads, futexes, signals, clocks, and glibc ABI
- Loading Qt or any HOffice executable
- AppKit rendering, input, clipboard, Korean IME, or document lifecycle

Those are M2 and later milestones.
