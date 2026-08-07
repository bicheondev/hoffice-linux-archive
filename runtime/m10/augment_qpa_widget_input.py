#!/usr/bin/env python3
"""Add an opt-in QWidget-aware input fallback to the hrtappkit QPA.

The ordinary QWindowSystemInterface path remains the production default.  When
``HRT_M10_DIRECT_WIDGET_INPUT=1`` is set, M10 can additionally resolve the
actual QWidget below a macOS event, deliver mouse events directly to that
widget, and route rejected keys to ``QApplication::focusWidget()``.  This is
needed to distinguish a platform-window transport problem from HWord's own
widget-focus policy without changing the stable 88-byte input ABI.

Every source rewrite is exact-anchor and fail closed.
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
    if "HRT M10 WIDGET:" in text:
        raise SystemExit("QWidget-aware M10 transport is already present")

    text = replace_once(
        text,
        '#include <QtGui/qwindow.h>\n#include <qpa/qwindowsysteminterface.h>\n',
        '#include <QtGui/qwindow.h>\n'
        '#include <QtWidgets/qabstractbutton.h>\n'
        '#include <QtWidgets/qaction.h>\n'
        '#include <QtWidgets/qapplication.h>\n'
        '#include <QtWidgets/qtoolbutton.h>\n'
        '#include <QtWidgets/qwidget.h>\n'
        '#include <qpa/qwindowsysteminterface.h>\n',
        "Qt Widgets includes",
    )

    helper_anchor = '''static void m10ActivateDeliveryWindow(QWindow *deliveryWindow,
                                      const char *phase)
'''
    helpers = r'''static bool m10DirectWidgetInputEnabled()
{
    static const bool enabled =
        qEnvironmentVariableIntValue("HRT_M10_DIRECT_WIDGET_INPUT") == 1;
    return enabled;
}

static QWidget *m10TopLevelWidgetForWindow(QWindow *deliveryWindow)
{
    if (deliveryWindow == nullptr)
        return nullptr;
    const QWidgetList widgets = QApplication::topLevelWidgets();
    for (QWidget *widget : widgets) {
        if (widget != nullptr && widget->windowHandle() == deliveryWindow)
            return widget;
    }
    return nullptr;
}

static void m10LogWidget(const char *phase, QWidget *widget,
                         const QPoint &topLevelPoint)
{
    if (widget == nullptr) {
        qWarning("HRT M10 WIDGET: phase=%s receiver=(null) point=%d,%d",
                 phase, topLevelPoint.x(), topLevelPoint.y());
        return;
    }

    const QByteArray name = widget->objectName().toUtf8();
    const char *className = widget->metaObject()->className();
    const QRect geometry = widget->geometry();
    QToolButton *toolButton = qobject_cast<QToolButton *>(widget);
    QAction *action = toolButton != nullptr ? toolButton->defaultAction()
                                            : nullptr;
    const QByteArray buttonText = toolButton != nullptr
        ? toolButton->text().toUtf8() : QByteArray();
    const QByteArray actionText = action != nullptr
        ? action->text().toUtf8() : QByteArray();
    const QByteArray actionName = action != nullptr
        ? action->objectName().toUtf8() : QByteArray();
    const QByteArray shortcut = action != nullptr
        ? action->shortcut().toString(QKeySequence::PortableText).toUtf8()
        : QByteArray();

    qWarning("HRT M10 WIDGET: phase=%s receiver=%p class=%s name=%s enabled=%d visible=%d focus-policy=%d geometry=%d,%d,%d,%d point=%d,%d button-text=%s action=%p action-name=%s action-text=%s action-enabled=%d shortcut=%s",
             phase,
             static_cast<void *>(widget), className, name.constData(),
             widget->isEnabled() ? 1 : 0,
             widget->isVisible() ? 1 : 0,
             int(widget->focusPolicy()),
             geometry.x(), geometry.y(), geometry.width(), geometry.height(),
             topLevelPoint.x(), topLevelPoint.y(), buttonText.constData(),
             static_cast<void *>(action), actionName.constData(),
             actionText.constData(),
             action != nullptr && action->isEnabled() ? 1 : 0,
             shortcut.constData());
}

static bool m10DeliverMouseToWidget(QWindow *deliveryWindow,
                                    QEvent::Type type,
                                    const QPointF &windowLocal,
                                    const QPointF &global,
                                    Qt::MouseButton changed,
                                    Qt::MouseButtons buttons,
                                    Qt::KeyboardModifiers modifiers)
{
    QWidget *topLevel = m10TopLevelWidgetForWindow(deliveryWindow);
    if (topLevel == nullptr) {
        qWarning("HRT M10 WIDGET: no top-level QWidget for window=%p",
                 static_cast<void *>(deliveryWindow));
        return false;
    }

    const QPoint topPoint = windowLocal.toPoint();
    QWidget *receiver = topLevel->childAt(topPoint);
    if (receiver == nullptr)
        receiver = topLevel;
    m10LogWidget("mouse-target", receiver, topPoint);

    if (type == QEvent::MouseButtonPress && receiver->isEnabled() &&
        receiver->focusPolicy() != Qt::NoFocus) {
        receiver->setFocus(Qt::MouseFocusReason);
    }

    const QPoint receiverPoint = receiver->mapFrom(topLevel, topPoint);
    QMouseEvent directEvent(type,
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
    QWidget *focusWidget = QApplication::focusWidget();
    qWarning("HRT M10 WIDGET: mouse delivered receiver=%p notified=%d accepted=%d type=%d focus-widget=%p focus-class=%s",
             static_cast<void *>(receiver),
             notified ? 1 : 0,
             accepted ? 1 : 0,
             int(type),
             static_cast<void *>(focusWidget),
             focusWidget != nullptr
                 ? focusWidget->metaObject()->className() : "(null)");
    return notified && accepted;
}

static void m10ActivateDeliveryWindow(QWindow *deliveryWindow,
                                      const char *phase)
'''
    text = replace_once(text, helper_anchor, helpers,
                        "QWidget helper insertion")

    key_receiver_anchor = '''    QObject *receiver = QGuiApplication::focusObject();
    if (receiver == nullptr) {
        qWarning("HRT M10 QPA: direct key fallback skipped: no focus object");
        return false;
    }
'''
    key_receiver = '''    QWidget *focusWidget = m10DirectWidgetInputEnabled()
        ? QApplication::focusWidget() : nullptr;
    QObject *receiver = focusWidget != nullptr
        ? static_cast<QObject *>(focusWidget)
        : QGuiApplication::focusObject();
    if (receiver == nullptr) {
        qWarning("HRT M10 QPA: direct key fallback skipped: no focus receiver");
        return false;
    }
    if (focusWidget != nullptr)
        m10LogWidget("key-target", focusWidget, QPoint(-1, -1));
'''
    text = replace_once(text, key_receiver_anchor, key_receiver,
                        "QWidget key receiver")

    mouse_anchor = '''            QWindowSystemInterface::handleMouseEvent<
                QWindowSystemInterface::SynchronousDelivery>(
                    deliveryWindow, local, global,
                    m8Buttons(event.buttons), changed, type, modifiers,
                    Qt::MouseEventNotSynthesized);
            if (event.action == HRT_M8_MOUSE_UP) {
'''
    mouse_replacement = '''            const bool widgetAccepted = m10DirectWidgetInputEnabled()
                ? m10DeliverMouseToWidget(
                      deliveryWindow, type, local, global, changed,
                      m8Buttons(event.buttons), modifiers)
                : false;
            if (!m10DirectWidgetInputEnabled()) {
                QWindowSystemInterface::handleMouseEvent<
                    QWindowSystemInterface::SynchronousDelivery>(
                        deliveryWindow, local, global,
                        m8Buttons(event.buttons), changed, type, modifiers,
                        Qt::MouseEventNotSynthesized);
            }
            if (event.action == HRT_M8_MOUSE_UP) {
'''
    text = replace_once(text, mouse_anchor, mouse_replacement,
                        "QWidget mouse delivery")

    mouse_log_anchor = '''            qWarning("HRT M8 QPA: mouse event delivered sequence=%llu action=%u button=0x%x buttons=0x%x local=%d,%d global=%d,%d focus-window=%p focus-object=%p focus-class=%s",
                     static_cast<unsigned long long>(event.sequence),
                     event.action, event.button, event.buttons,
                     event.x, event.y, event.global_x, event.global_y,
                     static_cast<void *>(QGuiApplication::focusWindow()),
                     static_cast<void *>(focusObject), focusClass);
'''
    mouse_log_replacement = '''            qWarning("HRT M8 QPA: mouse event delivered sequence=%llu action=%u button=0x%x buttons=0x%x local=%d,%d global=%d,%d widget-accepted=%d focus-window=%p focus-object=%p focus-class=%s",
                     static_cast<unsigned long long>(event.sequence),
                     event.action, event.button, event.buttons,
                     event.x, event.y, event.global_x, event.global_y,
                     widgetAccepted ? 1 : 0,
                     static_cast<void *>(QGuiApplication::focusWindow()),
                     static_cast<void *>(focusObject), focusClass);
'''
    text = replace_once(text, mouse_log_anchor, mouse_log_replacement,
                        "QWidget mouse result logging")

    required = {
        "HRT M10 WIDGET:": 5,
        "QApplication::focusWidget()": 2,
        "QApplication::topLevelWidgets()": 1,
        "m10DeliverMouseToWidget(": 2,
        "widget-accepted=%d": 1,
        "HRT_M10_DIRECT_WIDGET_INPUT": 1,
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
