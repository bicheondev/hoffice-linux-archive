#!/usr/bin/env python3
"""Add a fail-closed QInputMethodEvent fallback for printable HWord input.

The delayed-focus M11 frontier reaches the real ``hanul::DocumentTabImpl`` and
its direct mouse press/release path, but a printable QKeyEvent remains ignored.
This transform leaves ordinary key delivery first.  Only when a KeyPress with
non-empty text is rejected does it query the focused object for Qt input-method
state and deliver one QInputMethodEvent commit string to the same receiver.

The fallback is intentionally diagnostic and one-shot per host key press.  It
records both the input-method query and commit acceptance so a repaint alone
cannot be mistaken for text acceptance.  The 88-byte host transport ABI and
all non-printable key paths remain unchanged.
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
    if "HRT M11 IME:" in text:
        raise SystemExit("M11 input-method fallback is already present")

    include_anchor = '''#include <QtCore/qstring.h>
#include <QtGui/qevent.h>
'''
    include_replacement = '''#include <QtCore/qstring.h>
#include <QtCore/qvariant.h>
#include <QtGui/qevent.h>
'''
    text = replace_once(text, include_anchor, include_replacement,
                        "QVariant include")

    helper_anchor = '''static bool m10DeliverKeyToFocusObject(QEvent::Type type,
                                       int key,
'''
    helper = r'''static bool m11DeliverInputMethodCommit(QObject *receiver,
                                             const QString &text)
{
    if (receiver == nullptr || text.isEmpty())
        return false;

    const Qt::InputMethodQueries queries =
        Qt::ImEnabled |
        Qt::ImCursorRectangle |
        Qt::ImAnchorRectangle |
        Qt::ImSurroundingText |
        Qt::ImCurrentSelection |
        Qt::ImCursorPosition |
        Qt::ImAnchorPosition;
    QInputMethodQueryEvent queryEvent(queries);
    queryEvent.setAccepted(false);
    const bool queryNotified =
        QCoreApplication::sendEvent(receiver, &queryEvent);
    const QVariant enabledValue = queryEvent.value(Qt::ImEnabled);
    const QVariant cursorValue = queryEvent.value(Qt::ImCursorRectangle);
    const QVariant anchorValue = queryEvent.value(Qt::ImAnchorRectangle);
    const QVariant surroundingValue = queryEvent.value(Qt::ImSurroundingText);
    const QVariant selectionValue = queryEvent.value(Qt::ImCurrentSelection);
    const QVariant cursorPosition = queryEvent.value(Qt::ImCursorPosition);
    const QVariant anchorPosition = queryEvent.value(Qt::ImAnchorPosition);
    const QRectF cursorRectangle = cursorValue.toRectF();
    const QRectF anchorRectangle = anchorValue.toRectF();
    const QByteArray receiverName = receiver->objectName().toUtf8();

    qWarning("HRT M11 IME: query receiver=%p class=%s name=%s notified=%d accepted=%d enabled-valid=%d enabled=%d cursor-valid=%d cursor=%g,%g,%g,%g anchor-valid=%d anchor=%g,%g,%g,%g surrounding-valid=%d surrounding-length=%d selection-valid=%d selection-length=%d cursor-position-valid=%d cursor-position=%d anchor-position-valid=%d anchor-position=%d",
             static_cast<void *>(receiver),
             receiver->metaObject()->className(), receiverName.constData(),
             queryNotified ? 1 : 0, queryEvent.isAccepted() ? 1 : 0,
             enabledValue.isValid() ? 1 : 0,
             enabledValue.isValid() && enabledValue.toBool() ? 1 : 0,
             cursorValue.isValid() ? 1 : 0,
             cursorRectangle.x(), cursorRectangle.y(),
             cursorRectangle.width(), cursorRectangle.height(),
             anchorValue.isValid() ? 1 : 0,
             anchorRectangle.x(), anchorRectangle.y(),
             anchorRectangle.width(), anchorRectangle.height(),
             surroundingValue.isValid() ? 1 : 0,
             surroundingValue.toString().size(),
             selectionValue.isValid() ? 1 : 0,
             selectionValue.toString().size(),
             cursorPosition.isValid() ? 1 : 0,
             cursorPosition.toInt(),
             anchorPosition.isValid() ? 1 : 0,
             anchorPosition.toInt());

    QInputMethodEvent inputMethodEvent;
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
}

static bool m10DeliverKeyToFocusObject(QEvent::Type type,
                                       int key,
'''
    text = replace_once(text, helper_anchor, helper,
                        "input-method helper insertion")

    dispatch_anchor = '''    QKeyEvent directEvent(type, key, modifiers, text, false, 1u);
    directEvent.setAccepted(false);
    const bool notified = QCoreApplication::sendEvent(receiver, &directEvent);
    QCoreApplication::processEvents(QEventLoop::AllEvents, 2);
    const bool accepted = directEvent.isAccepted();
    const char *receiverClass = receiver->metaObject()->className();
    const QByteArray receiverName = receiver->objectName().toUtf8();
    qWarning("HRT M10 QPA: direct key fallback receiver=%p class=%s name=%s notified=%d accepted=%d type=%d key=0x%x text=%s",
             static_cast<void *>(receiver),
             receiverClass,
             receiverName.constData(),
             notified ? 1 : 0,
             accepted ? 1 : 0,
             int(type),
             key,
             text.toUtf8().constData());
    return notified && accepted;
'''
    dispatch_replacement = '''    QKeyEvent directEvent(type, key, modifiers, text, false, 1u);
    directEvent.setAccepted(false);
    const bool notified = QCoreApplication::sendEvent(receiver, &directEvent);
    QCoreApplication::processEvents(QEventLoop::AllEvents, 2);
    const bool accepted = directEvent.isAccepted();
    const bool inputMethodAccepted =
        !accepted && type == QEvent::KeyPress && !text.isEmpty()
            ? m11DeliverInputMethodCommit(receiver, text)
            : false;
    const char *receiverClass = receiver->metaObject()->className();
    const QByteArray receiverName = receiver->objectName().toUtf8();
    qWarning("HRT M10 QPA: direct key fallback receiver=%p class=%s name=%s notified=%d accepted=%d ime-accepted=%d type=%d key=0x%x text=%s",
             static_cast<void *>(receiver),
             receiverClass,
             receiverName.constData(),
             notified ? 1 : 0,
             accepted ? 1 : 0,
             inputMethodAccepted ? 1 : 0,
             int(type),
             key,
             text.toUtf8().constData());
    return notified && (accepted || inputMethodAccepted);
'''
    text = replace_once(text, dispatch_anchor, dispatch_replacement,
                        "input-method fallback dispatch")

    required = {
        "HRT M11 IME:": 2,
        "m11DeliverInputMethodCommit(": 2,
        "QInputMethodQueryEvent queryEvent": 1,
        "QInputMethodEvent inputMethodEvent": 1,
        "inputMethodEvent.setCommitString(text);": 1,
        "ime-accepted=%d": 1,
        "type == QEvent::KeyPress": 1,
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
