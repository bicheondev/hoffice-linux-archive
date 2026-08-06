# HOffice Runtime M4 — Qt offscreen probe

M4 begins immediately after the verified original HWord ELF entry. The first
probe supplies the package's exact Qt 5.11.3 `offscreen` QPA plugin, enables
Qt plugin diagnostics, and runs the unchanged HWord process beyond its entry
point under the clean-room Linux ABI bridge.

The probe is not a graphical macOS port. It establishes the next exact
boundary: whether Qt Core/Gui/Widgets and a real package QPA plugin can be
initialized before an AppKit-backed QPA implementation is substituted.
