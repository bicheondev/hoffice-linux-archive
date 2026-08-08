#!/usr/bin/env python3
"""Add deterministic event-loop boundaries to staged HWord input.

HWord repaints synchronously while the blank-document toolbar button is being
clicked.  The AppKit test adapter observes that repaint and queues the next
mouse stage before ``QAbstractButton::click()`` has returned.  Even with the
recursive-drain guard, the outer FIFO loop would then consume the document
click and key in the same call, while the document view had not yet been
constructed.

This final QPA generation pass yields after every mouse-up and schedules a
zero-delay ``QWindow::requestUpdate()``.  The next queued stage is therefore
consumed only after the current Qt handler has unwound and the application has
completed any synchronous model/widget creation.  The production ABI and the
real AppKit event path are unchanged; only batching inside the custom QPA is
altered.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M11 QPA: mouse-up stage boundary" in text:
        raise SystemExit("M11 staged-input boundary is already present")

    text = replace_once(
        text,
        "#include <QtCore/qstring.h>\n",
        "#include <QtCore/qstring.h>\n#include <QtCore/qtimer.h>\n",
        "QTimer include",
    )

    anchor = '''            qWarning("HRT M8 QPA: mouse event delivered sequence=%llu action=%u button=0x%x buttons=0x%x local=%d,%d global=%d,%d widget-accepted=%d focus-window=%p focus-object=%p focus-class=%s",
                     static_cast<unsigned long long>(event.sequence),
                     event.action, event.button, event.buttons,
                     event.x, event.y, event.global_x, event.global_y,
                     widgetAccepted ? 1 : 0,
                     static_cast<void *>(QGuiApplication::focusWindow()),
                     static_cast<void *>(focusObject), focusClass);
'''
    replacement = anchor + '''            if (event.action == HRT_M8_MOUSE_UP) {
                QPointer<QWindow> updateWindow(deliveryWindow);
                QTimer::singleShot(0, [updateWindow]() {
                    if (!updateWindow.isNull())
                        updateWindow->requestUpdate();
                });
                qWarning("HRT M11 QPA: mouse-up stage boundary sequence=%llu key=%llu mouse=%llu",
                         static_cast<unsigned long long>(event.sequence),
                         static_cast<unsigned long long>(m_keyEventsDelivered),
                         static_cast<unsigned long long>(m_mouseEventsDelivered));
                return;
            }
'''
    text = replace_once(
        text, anchor, replacement,
        "post-mouse delivery stage boundary",
    )

    text = replace_once(
        text,
        "#include <QtCore/qeventloop.h>\n",
        "#include <QtCore/qeventloop.h>\n#include <QtCore/qpointer.h>\n",
        "QPointer include",
    )

    required = {
        "HRT M11 QPA: mouse-up stage boundary": 1,
        "QTimer::singleShot(0": 1,
        "QPointer<QWindow> updateWindow": 1,
        "updateWindow->requestUpdate();": 1,
        "widget-accepted=%d": 1,
        "abstract button click invoked": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"M11 QPA marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
