#!/usr/bin/env python3
"""Refine the QWidget-aware hrtappkit input path for exact HWord.

The first QWidget replay proved that the 800×600 HWord window receives all
mouse events in strict order, but two details remained ambiguous:

* the ``新建`` QToolButton had no default QAction and a synthetic QMouseEvent
  sequence could be accepted without emitting the application signal; and
* the document point resolved to a non-focusable QStackedWidget, leaving the
  toolbar button as QApplication::focusWidget().

This fail-closed generator is applied after ``augment_qpa_widget_input.py``.
It gives QAbstractButton a deterministic press/release/click path and inventories
all visible widgets containing the event point.  The deepest enabled focusable
candidate is explicitly focused before key delivery.  Real AppKit events still
use the same 88-byte opcode-262 transport and the normal QPA event loop.
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
    if "HRT M10 FOCUS:" in text:
        raise SystemExit("M10 deterministic button/focus refinement is already present")

    helper_anchor = '''static bool m10DeliverMouseToWidget(QWindow *deliveryWindow,
                                    QEvent::Type type,
'''
    helpers = r'''static int m10WidgetDepth(QWidget *widget, QWidget *topLevel)
{
    int depth = 0;
    QWidget *cursor = widget;
    while (cursor != nullptr && cursor != topLevel) {
        ++depth;
        cursor = cursor->parentWidget();
    }
    return cursor == topLevel ? depth : -1;
}

static QRect m10WidgetRectInTopLevel(QWidget *widget, QWidget *topLevel)
{
    if (widget == nullptr || topLevel == nullptr)
        return QRect();
    return QRect(widget->mapTo(topLevel, QPoint(0, 0)), widget->size());
}

static QWidget *m10BestFocusableWidgetAt(QWidget *topLevel,
                                         QWidget *receiver,
                                         const QPoint &topPoint,
                                         bool logCandidates)
{
    QWidget *best = nullptr;
    int bestDepth = -1;
    qint64 bestArea = std::numeric_limits<qint64>::max();

    QWidgetList candidates = topLevel->findChildren<QWidget *>();
    candidates.prepend(topLevel);
    for (QWidget *candidate : candidates) {
        if (candidate == nullptr || !candidate->isVisible() ||
            !candidate->isEnabled()) {
            continue;
        }
        const QRect rect = m10WidgetRectInTopLevel(candidate, topLevel);
        if (!rect.contains(topPoint))
            continue;

        const int depth = m10WidgetDepth(candidate, topLevel);
        const qint64 area = qint64(qMax(1, rect.width())) *
                            qint64(qMax(1, rect.height()));
        const QByteArray name = candidate->objectName().toUtf8();
        if (logCandidates) {
            qWarning("HRT M10 FOCUS: candidate=%p class=%s name=%s depth=%d focus-policy=%d enabled=%d visible=%d rect=%d,%d,%d,%d point=%d,%d",
                     static_cast<void *>(candidate),
                     candidate->metaObject()->className(),
                     name.constData(), depth, int(candidate->focusPolicy()),
                     candidate->isEnabled() ? 1 : 0,
                     candidate->isVisible() ? 1 : 0,
                     rect.x(), rect.y(), rect.width(), rect.height(),
                     topPoint.x(), topPoint.y());
        }

        if (candidate->focusPolicy() == Qt::NoFocus)
            continue;
        if (depth > bestDepth || (depth == bestDepth && area < bestArea)) {
            best = candidate;
            bestDepth = depth;
            bestArea = area;
        }
    }

    if (best == nullptr && receiver != nullptr) {
        const QWidgetList descendants = receiver->findChildren<QWidget *>();
        for (QWidget *candidate : descendants) {
            if (candidate == nullptr || !candidate->isVisible() ||
                !candidate->isEnabled() ||
                candidate->focusPolicy() == Qt::NoFocus) {
                continue;
            }
            const int depth = m10WidgetDepth(candidate, topLevel);
            const QRect rect = m10WidgetRectInTopLevel(candidate, topLevel);
            const qint64 area = qint64(qMax(1, rect.width())) *
                                qint64(qMax(1, rect.height()));
            if (depth > bestDepth || (depth == bestDepth && area < bestArea)) {
                best = candidate;
                bestDepth = depth;
                bestArea = area;
            }
        }
    }

    qWarning("HRT M10 FOCUS: selected receiver=%p selected=%p class=%s focus-policy=%d point=%d,%d",
             static_cast<void *>(receiver), static_cast<void *>(best),
             best != nullptr ? best->metaObject()->className() : "(null)",
             best != nullptr ? int(best->focusPolicy()) : -1,
             topPoint.x(), topPoint.y());
    return best;
}

static bool m10DeliverMouseToWidget(QWindow *deliveryWindow,
                                    QEvent::Type type,
'''
    text = replace_once(text, helper_anchor, helpers,
                        "focus-candidate helper insertion")

    include_anchor = '''#include <QtWidgets/qwidget.h>
#include <qpa/qwindowsysteminterface.h>
'''
    include_replacement = '''#include <QtWidgets/qwidget.h>
#include <limits>
#include <qpa/qwindowsysteminterface.h>
'''
    text = replace_once(text, include_anchor, include_replacement,
                        "numeric limits include")

    focus_anchor = '''    if (type == QEvent::MouseButtonPress && receiver->isEnabled() &&
        receiver->focusPolicy() != Qt::NoFocus) {
        receiver->setFocus(Qt::MouseFocusReason);
    }

    const QPoint receiverPoint = receiver->mapFrom(topLevel, topPoint);
'''
    focus_replacement = '''    QWidget *focusTarget = m10BestFocusableWidgetAt(
        topLevel, receiver, topPoint, type == QEvent::MouseButtonRelease);
    if (type == QEvent::MouseButtonPress && focusTarget != nullptr) {
        focusTarget->setFocus(Qt::MouseFocusReason);
        qWarning("HRT M10 FOCUS: explicit focus target=%p class=%s actual=%p actual-class=%s",
                 static_cast<void *>(focusTarget),
                 focusTarget->metaObject()->className(),
                 static_cast<void *>(QApplication::focusWidget()),
                 QApplication::focusWidget() != nullptr
                     ? QApplication::focusWidget()->metaObject()->className()
                     : "(null)");
    }

    const QPoint receiverPoint = receiver->mapFrom(topLevel, topPoint);
'''
    text = replace_once(text, focus_anchor, focus_replacement,
                        "focus-target selection")

    dispatch_anchor = '''    QMouseEvent directEvent(type,
                            QPointF(receiverPoint),
                            windowLocal,
                            global,
                            changed,
                            buttons,
                            modifiers,
                            Qt::MouseEventNotSynthesized);
    directEvent.setAccepted(false);
    const bool notified = QCoreApplication::sendEvent(receiver, &directEvent);
    if (type == QEvent::MouseButtonRelease)
        QCoreApplication::processEvents(QEventLoop::AllEvents, 3);
    const bool accepted = directEvent.isAccepted();
'''
    dispatch_replacement = '''    QAbstractButton *abstractButton =
        qobject_cast<QAbstractButton *>(receiver);
    bool notified = false;
    bool accepted = false;
    if (abstractButton != nullptr && changed == Qt::LeftButton &&
        type == QEvent::MouseButtonPress) {
        abstractButton->setDown(true);
        notified = true;
        accepted = true;
        qWarning("HRT M10 FOCUS: abstract button press receiver=%p text=%s",
                 static_cast<void *>(abstractButton),
                 abstractButton->text().toUtf8().constData());
    } else if (abstractButton != nullptr && changed == Qt::LeftButton &&
               type == QEvent::MouseButtonRelease) {
        abstractButton->setDown(false);
        abstractButton->click();
        QCoreApplication::processEvents(QEventLoop::AllEvents, 5);
        notified = true;
        accepted = true;
        qWarning("HRT M10 FOCUS: abstract button click invoked receiver=%p text=%s checked=%d",
                 static_cast<void *>(abstractButton),
                 abstractButton->text().toUtf8().constData(),
                 abstractButton->isChecked() ? 1 : 0);
    } else {
        QMouseEvent directEvent(type,
                                QPointF(receiverPoint),
                                windowLocal,
                                global,
                                changed,
                                buttons,
                                modifiers,
                                Qt::MouseEventNotSynthesized);
        directEvent.setAccepted(false);
        notified = QCoreApplication::sendEvent(receiver, &directEvent);
        if (type == QEvent::MouseButtonRelease)
            QCoreApplication::processEvents(QEventLoop::AllEvents, 3);
        accepted = directEvent.isAccepted();
    }
'''
    text = replace_once(text, dispatch_anchor, dispatch_replacement,
                        "deterministic abstract-button dispatch")

    required = {
        "HRT M10 FOCUS:": 5,
        "abstract button click invoked": 1,
        "m10BestFocusableWidgetAt(": 2,
        "std::numeric_limits<qint64>::max()": 1,
        "abstractButton->click();": 1,
        "findChildren<QWidget *>()": 2,
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
