# HOffice Runtime M5C — custom Qt 5.11.3 QPA

M5C replaces the package's generic offscreen plugin with a clean-room
`hrtmac` platform plugin built against the exact Qt 5.11.3 private ABI.
The source base is the official `qt/qtbase` v5.11.3 commit
`08de243eaa007597c2bfbc97d3d14e2f821ac4be`.

The first gate keeps Qt's upstream offscreen raster/backing-store behavior,
but sends deterministic AppKit window requests through the M5 host-call
transport when the integration is created and when a Qt platform window is
shown. Passing the gate proves that the unchanged HWord process selected the
custom QPA plugin and that a request originated inside the Qt platform layer,
not from the earlier LD_PRELOAD proof constructor.

Pixel transport, input, clipboard, Korean IME, resize synchronization, and
native document lifecycle remain later M5/M6 gates.
