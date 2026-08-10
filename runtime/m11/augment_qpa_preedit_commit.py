#!/usr/bin/env python3
"""Precede the printable HWord IME commit with a real composition lifecycle.

The first M11 input-method probe established that ``hanul::DocumentTabImpl``
accepts ``QInputMethodQueryEvent`` with ``ImEnabled=true`` and a valid cursor
rectangle, while a standalone commit event is ignored.  Some custom editors
initialize their composition state only after a non-empty preedit event.

This final fail-closed transform changes only that diagnostic fallback: it
sends a cursor-bearing preedit string, lets Qt process resulting editor work,
then sends the same text as the commit string.  Ordinary key delivery remains
first and the fallback still runs only for a rejected printable KeyPress.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "HRT M11 COMPOSE:" in text:
        raise SystemExit("M11 preedit-to-commit lifecycle is already present")

    old = '''    QInputMethodEvent inputMethodEvent;
    inputMethodEvent.setCommitString(text);
    inputMethodEvent.setAccepted(false);
    const bool notified =
        QCoreApplication::sendEvent(receiver, &inputMethodEvent);
    QCoreApplication::processEvents(QEventLoop::AllEvents, 8);
    const bool accepted = inputMethodEvent.isAccepted();
    qWarning("HRT M11 IME: commit receiver=%p class=%s notified=%d accepted=%d text=%s",
             static_cast<void *>(receiver),
             receiver->metaObject()->className(),
             notified ? 1 : 0, accepted ? 1 : 0,
             text.toUtf8().constData());
    return notified && accepted;
'''
    new = '''    QList<QInputMethodEvent::Attribute> attributes;
    attributes.append(QInputMethodEvent::Attribute(
        QInputMethodEvent::Cursor, text.size(), 1, QVariant()));
    QInputMethodEvent preeditEvent(text, attributes);
    preeditEvent.setAccepted(false);
    const bool preeditNotified =
        QGuiApplication::sendEvent(receiver, &preeditEvent);
    QCoreApplication::processEvents(QEventLoop::AllEvents, 12);
    const bool preeditAccepted = preeditEvent.isAccepted();
    qWarning("HRT M11 COMPOSE: preedit receiver=%p class=%s notified=%d accepted=%d text=%s",
             static_cast<void *>(receiver),
             receiver->metaObject()->className(),
             preeditNotified ? 1 : 0, preeditAccepted ? 1 : 0,
             text.toUtf8().constData());

    QInputMethodEvent inputMethodEvent;
    inputMethodEvent.setCommitString(text);
    inputMethodEvent.setAccepted(false);
    const bool notified =
        QGuiApplication::sendEvent(receiver, &inputMethodEvent);
    QCoreApplication::processEvents(QEventLoop::AllEvents, 16);
    const bool accepted = inputMethodEvent.isAccepted();
    qWarning("HRT M11 COMPOSE: commit receiver=%p class=%s notified=%d accepted=%d preedit-accepted=%d text=%s",
             static_cast<void *>(receiver),
             receiver->metaObject()->className(),
             notified ? 1 : 0, accepted ? 1 : 0,
             preeditAccepted ? 1 : 0,
             text.toUtf8().constData());
    return notified && accepted;
'''
    text = replace_once(text, old, new, "preedit-to-commit lifecycle")

    required = {
        "HRT M11 COMPOSE:": 2,
        "QInputMethodEvent preeditEvent": 1,
        "QInputMethodEvent inputMethodEvent": 1,
        "QInputMethodEvent::Cursor": 1,
        "QGuiApplication::sendEvent(receiver, &preeditEvent)": 1,
        "QGuiApplication::sendEvent(receiver, &inputMethodEvent)": 1,
        "preedit-accepted=%d": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"generated marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
