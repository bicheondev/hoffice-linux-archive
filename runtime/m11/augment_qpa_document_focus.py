#!/usr/bin/env python3
"""Repair delayed HWord document focus before staged key delivery.

The Korean-title M11 replay proved that the real blank-document command is
invoked and the document tab is created.  The document click can still arrive
one paint too early, while the QTabWidget has no focusable page child yet.  Qt
then forwards focus to its QTabBar and the later key event is correctly
rejected.

This third, fail-closed QPA transform records the non-toolbar document point.
Immediately before the first key event it inventories the now-materialized
widget hierarchy, prefers an enabled visible editor/view/canvas/viewport below
that point, gives a NoFocus canvas a diagnostic StrongFocus policy when needed,
replays the focus click on the selected widget, and only then lets the existing
QWidget key fallback run.  The transport ABI and ordinary production path are
unchanged.
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
    if "HRT M11 FOCUS:" in text:
        raise SystemExit("M11 delayed document-focus repair is already present")

    include_anchor = '''#include <QtWidgets/qwidget.h>
#include <limits>
#include <qpa/qwindowsysteminterface.h>
'''
    include_replacement = '''#include <QtWidgets/qwidget.h>
#include <QtWidgets/qabstractscrollarea.h>
#include <QtWidgets/qstackedwidget.h>
#include <QtWidgets/qtabbar.h>
#include <QtWidgets/qtabwidget.h>
#include <limits>
#include <qpa/qwindowsysteminterface.h>
'''
    text = replace_once(text, include_anchor, include_replacement,
                        "M11 document-focus includes")

    helper_anchor = '''static bool m10DeliverMouseToWidget(QWindow *deliveryWindow,
                                    QEvent::Type type,
'''
    helpers = r'''static QWidget *g_m11DocumentTopLevel = nullptr;
static QPoint g_m11DocumentPoint(-1, -1);
static bool g_m11DocumentPointValid = false;
static bool g_m11FocusRepairAttempted = false;

static bool m11IsContainerWidget(QWidget *widget)
{
    if (widget == nullptr)
        return true;
    return qobject_cast<QMainWindow *>(widget) != nullptr ||
           qobject_cast<QToolBar *>(widget) != nullptr ||
           qobject_cast<QToolButton *>(widget) != nullptr ||
           qobject_cast<QTabBar *>(widget) != nullptr ||
           qobject_cast<QTabWidget *>(widget) != nullptr ||
           qobject_cast<QStackedWidget *>(widget) != nullptr;
}

static int m11DocumentCandidateScore(QWidget *candidate,
                                     QWidget *topLevel,
                                     const QPoint &topPoint)
{
    if (candidate == nullptr || topLevel == nullptr ||
        !candidate->isEnabled() || candidate->isHidden()) {
        return std::numeric_limits<int>::min();
    }

    const QRect rect = m10WidgetRectInTopLevel(candidate, topLevel);
    if (!rect.isValid() || !rect.contains(topPoint))
        return std::numeric_limits<int>::min();

    const QByteArray className(candidate->metaObject()->className());
    const QByteArray lowerClass = className.toLower();
    const QByteArray lowerName = candidate->objectName().toUtf8().toLower();
    const int depth = m10WidgetDepth(candidate, topLevel);
    if (depth < 0)
        return std::numeric_limits<int>::min();

    int score = depth * 40;
    if (candidate->isVisible()) score += 300;
    if (candidate->focusPolicy() != Qt::NoFocus) score += 240;
    if (candidate->testAttribute(Qt::WA_InputMethodEnabled)) score += 180;
    if (lowerName.contains("viewport")) score += 900;
    if (lowerClass.contains("editor") || lowerClass.contains("edit"))
        score += 1100;
    if (lowerClass.contains("canvas")) score += 1000;
    if (lowerClass.contains("document")) score += 700;
    if (lowerClass.contains("view")) score += 650;
    if (lowerClass.contains("page")) score += 550;
    if (lowerClass.contains("hwp") || lowerClass.contains("word"))
        score += 450;
    if (qobject_cast<QAbstractScrollArea *>(candidate) != nullptr)
        score += 350;
    if (m11IsContainerWidget(candidate)) score -= 1600;

    const qint64 area = qint64(qMax(1, rect.width())) *
                        qint64(qMax(1, rect.height()));
    score -= int(qMin<qint64>(area / 50000, 120));
    return score;
}

static QWidget *m11BestDocumentWidget(QWidget *topLevel,
                                      const QPoint &topPoint)
{
    QWidget *best = nullptr;
    int bestScore = std::numeric_limits<int>::min();
    QWidgetList candidates = topLevel->findChildren<QWidget *>();
    candidates.prepend(topLevel);

    for (QWidget *candidate : candidates) {
        const QRect rect = m10WidgetRectInTopLevel(candidate, topLevel);
        const int score = m11DocumentCandidateScore(
            candidate, topLevel, topPoint);
        if (score == std::numeric_limits<int>::min())
            continue;
        const QByteArray name = candidate->objectName().toUtf8();
        qWarning("HRT M11 FOCUS: candidate=%p class=%s name=%s depth=%d score=%d focus-policy=%d input-method=%d visible=%d rect=%d,%d,%d,%d point=%d,%d",
                 static_cast<void *>(candidate),
                 candidate->metaObject()->className(), name.constData(),
                 m10WidgetDepth(candidate, topLevel), score,
                 int(candidate->focusPolicy()),
                 candidate->testAttribute(Qt::WA_InputMethodEnabled) ? 1 : 0,
                 candidate->isVisible() ? 1 : 0,
                 rect.x(), rect.y(), rect.width(), rect.height(),
                 topPoint.x(), topPoint.y());
        if (score > bestScore) {
            best = candidate;
            bestScore = score;
        }
    }

    qWarning("HRT M11 FOCUS: selected=%p class=%s score=%d point=%d,%d",
             static_cast<void *>(best),
             best != nullptr ? best->metaObject()->className() : "(null)",
             bestScore, topPoint.x(), topPoint.y());
    return best;
}

static QWidget *m11RepairDocumentFocus(QWidget *currentFocus)
{
    if (g_m11FocusRepairAttempted || !g_m11DocumentPointValid ||
        g_m11DocumentTopLevel == nullptr) {
        return currentFocus;
    }
    g_m11FocusRepairAttempted = true;

    QWidget *target = m11BestDocumentWidget(
        g_m11DocumentTopLevel, g_m11DocumentPoint);
    if (target == nullptr || m11IsContainerWidget(target)) {
        qWarning("HRT M11 FOCUS: repair skipped current=%p current-class=%s target=%p target-class=%s",
                 static_cast<void *>(currentFocus),
                 currentFocus != nullptr
                     ? currentFocus->metaObject()->className() : "(null)",
                 static_cast<void *>(target),
                 target != nullptr ? target->metaObject()->className()
                                   : "(null)");
        return currentFocus;
    }

    if (QAbstractScrollArea *area =
            qobject_cast<QAbstractScrollArea *>(target)) {
        if (area->viewport() != nullptr)
            target = area->viewport();
    }
    QWidget *proxy = target->focusProxy();
    if (proxy != nullptr && !m11IsContainerWidget(proxy))
        target = proxy;

    const Qt::FocusPolicy oldPolicy = target->focusPolicy();
    if (oldPolicy == Qt::NoFocus)
        target->setFocusPolicy(Qt::StrongFocus);
    target->setAttribute(Qt::WA_InputMethodEnabled, true);
    target->setFocus(Qt::MouseFocusReason);
    QCoreApplication::processEvents(QEventLoop::AllEvents, 5);

    const QPoint localPoint = target->mapFrom(
        g_m11DocumentTopLevel, g_m11DocumentPoint);
    const QPoint globalPoint = g_m11DocumentTopLevel->mapToGlobal(
        g_m11DocumentPoint);
    QMouseEvent pressEvent(QEvent::MouseButtonPress,
                           QPointF(localPoint),
                           QPointF(g_m11DocumentPoint),
                           QPointF(globalPoint),
                           Qt::LeftButton, Qt::LeftButton,
                           Qt::NoModifier,
                           Qt::MouseEventNotSynthesized);
    pressEvent.setAccepted(false);
    QCoreApplication::sendEvent(target, &pressEvent);
    QMouseEvent releaseEvent(QEvent::MouseButtonRelease,
                             QPointF(localPoint),
                             QPointF(g_m11DocumentPoint),
                             QPointF(globalPoint),
                             Qt::LeftButton, Qt::NoButton,
                             Qt::NoModifier,
                             Qt::MouseEventNotSynthesized);
    releaseEvent.setAccepted(false);
    QCoreApplication::sendEvent(target, &releaseEvent);
    QCoreApplication::processEvents(QEventLoop::AllEvents, 8);

    QWidget *actual = QApplication::focusWidget();
    qWarning("HRT M11 FOCUS: repaired target=%p class=%s old-policy=%d actual=%p actual-class=%s press-accepted=%d release-accepted=%d",
             static_cast<void *>(target), target->metaObject()->className(),
             int(oldPolicy), static_cast<void *>(actual),
             actual != nullptr ? actual->metaObject()->className() : "(null)",
             pressEvent.isAccepted() ? 1 : 0,
             releaseEvent.isAccepted() ? 1 : 0);
    return actual != nullptr ? actual : target;
}

static bool m10DeliverMouseToWidget(QWindow *deliveryWindow,
                                    QEvent::Type type,
'''
    text = replace_once(text, helper_anchor, helpers,
                        "M11 document-focus helper insertion")

    point_anchor = '''    m10LogWidget("mouse-target", receiver, topPoint);

    QWidget *focusTarget = m10BestFocusableWidgetAt(
'''
    point_replacement = '''    m10LogWidget("mouse-target", receiver, topPoint);
    if (type == QEvent::MouseButtonRelease &&
        qobject_cast<QAbstractButton *>(receiver) == nullptr) {
        g_m11DocumentTopLevel = topLevel;
        g_m11DocumentPoint = topPoint;
        g_m11DocumentPointValid = true;
        g_m11FocusRepairAttempted = false;
        qWarning("HRT M11 FOCUS: recorded document point receiver=%p class=%s point=%d,%d",
                 static_cast<void *>(receiver),
                 receiver->metaObject()->className(),
                 topPoint.x(), topPoint.y());
    }

    QWidget *focusTarget = m10BestFocusableWidgetAt(
'''
    text = replace_once(text, point_anchor, point_replacement,
                        "M11 document point recording")

    key_anchor = '''    QWidget *focusWidget = m10DirectWidgetInputEnabled()
        ? QApplication::focusWidget() : nullptr;
    QObject *receiver = focusWidget != nullptr
'''
    key_replacement = '''    QWidget *focusWidget = m10DirectWidgetInputEnabled()
        ? QApplication::focusWidget() : nullptr;
    if (m10DirectWidgetInputEnabled())
        focusWidget = m11RepairDocumentFocus(focusWidget);
    QObject *receiver = focusWidget != nullptr
'''
    text = replace_once(text, key_anchor, key_replacement,
                        "M11 pre-key focus repair")

    required = {
        "HRT M11 FOCUS:": 5,
        "m11RepairDocumentFocus(": 2,
        "m11BestDocumentWidget(": 2,
        "g_m11DocumentPointValid": 3,
        "target->setFocusPolicy(Qt::StrongFocus);": 1,
        "QEvent::MouseButtonPress": 4,
        "qobject_cast<QAbstractButton *>(receiver)": 1,
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
