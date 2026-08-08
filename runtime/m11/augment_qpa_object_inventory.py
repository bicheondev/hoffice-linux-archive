#!/usr/bin/env python3
"""Inventory HWord's materialized document hierarchy before key delivery.

The staged replay now proves that the real blank-document command creates a
``hanul::DocumentTabImpl`` and a visible scrollable surface.  That container is
not itself the editor: its original focus policy and input-method attribute are
both disabled, and forcing those flags only manufactures a default QWidget
input-method query that still rejects preedit and commit events.

This fail-closed diagnostic pass runs once, immediately before delayed focus
selection.  It records every relevant QWidget, tab/stack current page, native
QWindow, non-widget Hancom QObject, and the class-local meta-object surface of
``hanul::DocumentTabImpl``.  No input target, focus policy, or event behavior is
changed by this pass.
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
    if "HRT M11 INVENTORY:" in text:
        raise SystemExit("M11 document object inventory is already present")

    include_anchor = '#include <QtCore/qvariant.h>\n'
    include_replacement = (
        '#include <QtCore/qvariant.h>\n'
        '#include <QtCore/qmetaobject.h>\n'
    )
    text = replace_once(text, include_anchor, include_replacement,
                        "QMetaObject include")

    helper_anchor = '''static bool m11IsContainerWidget(QWidget *widget)
'''
    helpers = r'''static bool g_m11InventoryCompleted = false;

static bool m11InterestingObjectName(const QByteArray &className,
                                     const QByteArray &objectName)
{
    const QByteArray value = (className + ' ' + objectName).toLower();
    return value.contains("hanul") || value.contains("hnc") ||
           value.contains("hwp") || value.contains("word") ||
           value.contains("document") || value.contains("editor") ||
           value.contains("edit") || value.contains("canvas") ||
           value.contains("view") || value.contains("page") ||
           value.contains("text") || value.contains("input") ||
           value.contains("tab") || value.contains("stack") ||
           value.contains("scroll");
}

static void m11LogClassMetaObject(QObject *object)
{
    if (object == nullptr)
        return;
    const QMetaObject *meta = object->metaObject();
    const QByteArray objectName = object->objectName().toUtf8();
    qWarning("HRT M11 META: object=%p class=%s name=%s method-offset=%d method-count=%d property-offset=%d property-count=%d class-info-offset=%d class-info-count=%d",
             static_cast<void *>(object), meta->className(),
             objectName.constData(), meta->methodOffset(),
             meta->methodCount(), meta->propertyOffset(),
             meta->propertyCount(), meta->classInfoOffset(),
             meta->classInfoCount());
    for (int index = meta->methodOffset(); index < meta->methodCount(); ++index) {
        const QMetaMethod method = meta->method(index);
        qWarning("HRT M11 META: method object=%p index=%d type=%d access=%d signature=%s",
                 static_cast<void *>(object), index, int(method.methodType()),
                 int(method.access()), method.methodSignature().constData());
    }
    for (int index = meta->propertyOffset(); index < meta->propertyCount(); ++index) {
        const QMetaProperty property = meta->property(index);
        qWarning("HRT M11 META: property object=%p index=%d name=%s type=%s readable=%d writable=%d notify=%d",
                 static_cast<void *>(object), index, property.name(),
                 property.typeName(), property.isReadable() ? 1 : 0,
                 property.isWritable() ? 1 : 0,
                 property.hasNotifySignal() ? 1 : 0);
    }
}

static void m11InventoryDocumentHierarchy(QWidget *topLevel,
                                          const QPoint &topPoint)
{
    if (g_m11InventoryCompleted || topLevel == nullptr)
        return;
    g_m11InventoryCompleted = true;

    QWidget *focusWidget = QApplication::focusWidget();
    QObject *focusObject = QGuiApplication::focusObject();
    qWarning("HRT M11 INVENTORY: begin top=%p class=%s point=%d,%d focus-widget=%p focus-widget-class=%s focus-object=%p focus-object-class=%s",
             static_cast<void *>(topLevel), topLevel->metaObject()->className(),
             topPoint.x(), topPoint.y(), static_cast<void *>(focusWidget),
             focusWidget != nullptr ? focusWidget->metaObject()->className()
                                    : "(null)",
             static_cast<void *>(focusObject),
             focusObject != nullptr ? focusObject->metaObject()->className()
                                    : "(null)");

    QWidgetList widgets = topLevel->findChildren<QWidget *>();
    widgets.prepend(topLevel);
    for (QWidget *widget : widgets) {
        if (widget == nullptr)
            continue;
        const QByteArray className(widget->metaObject()->className());
        const QByteArray objectName = widget->objectName().toUtf8();
        const QRect rect = m10WidgetRectInTopLevel(widget, topLevel);
        const bool underPoint = rect.isValid() && rect.contains(topPoint);
        QTabWidget *tabs = qobject_cast<QTabWidget *>(widget);
        QStackedWidget *stack = qobject_cast<QStackedWidget *>(widget);
        QAbstractScrollArea *scroll =
            qobject_cast<QAbstractScrollArea *>(widget);
        if (!underPoint && !m11InterestingObjectName(className, objectName) &&
            !widget->testAttribute(Qt::WA_InputMethodEnabled) &&
            tabs == nullptr && stack == nullptr && scroll == nullptr) {
            continue;
        }
        QWidget *parent = widget->parentWidget();
        QWidget *proxy = widget->focusProxy();
        QWindow *handle = widget->windowHandle();
        qWarning("HRT M11 INVENTORY: widget=%p class=%s name=%s parent=%p parent-class=%s depth=%d rect=%d,%d,%d,%d local=%d,%d,%d,%d under-point=%d visible=%d hidden=%d enabled=%d focus-policy=%d has-focus=%d input-method=%d proxy=%p proxy-class=%s native=%d handle=%p children=%d",
                 static_cast<void *>(widget), className.constData(),
                 objectName.constData(), static_cast<void *>(parent),
                 parent != nullptr ? parent->metaObject()->className()
                                   : "(null)",
                 m10WidgetDepth(widget, topLevel), rect.x(), rect.y(),
                 rect.width(), rect.height(), widget->geometry().x(),
                 widget->geometry().y(), widget->geometry().width(),
                 widget->geometry().height(), underPoint ? 1 : 0,
                 widget->isVisible() ? 1 : 0, widget->isHidden() ? 1 : 0,
                 widget->isEnabled() ? 1 : 0, int(widget->focusPolicy()),
                 widget->hasFocus() ? 1 : 0,
                 widget->testAttribute(Qt::WA_InputMethodEnabled) ? 1 : 0,
                 static_cast<void *>(proxy),
                 proxy != nullptr ? proxy->metaObject()->className()
                                  : "(null)",
                 widget->testAttribute(Qt::WA_NativeWindow) ? 1 : 0,
                 static_cast<void *>(handle), widget->children().size());

        if (tabs != nullptr) {
            QWidget *current = tabs->currentWidget();
            qWarning("HRT M11 INVENTORY: tab-widget=%p count=%d current-index=%d current=%p current-class=%s current-name=%s tabs-closable=%d movable=%d",
                     static_cast<void *>(tabs), tabs->count(),
                     tabs->currentIndex(), static_cast<void *>(current),
                     current != nullptr ? current->metaObject()->className()
                                        : "(null)",
                     current != nullptr
                         ? current->objectName().toUtf8().constData() : "",
                     tabs->tabsClosable() ? 1 : 0,
                     tabs->isMovable() ? 1 : 0);
        }
        if (stack != nullptr) {
            QWidget *current = stack->currentWidget();
            qWarning("HRT M11 INVENTORY: stacked-widget=%p count=%d current-index=%d current=%p current-class=%s current-name=%s",
                     static_cast<void *>(stack), stack->count(),
                     stack->currentIndex(), static_cast<void *>(current),
                     current != nullptr ? current->metaObject()->className()
                                        : "(null)",
                     current != nullptr
                         ? current->objectName().toUtf8().constData() : "");
        }
        if (scroll != nullptr) {
            QWidget *viewport = scroll->viewport();
            qWarning("HRT M11 INVENTORY: scroll-area=%p viewport=%p viewport-class=%s viewport-name=%s viewport-visible=%d viewport-focus-policy=%d viewport-input-method=%d",
                     static_cast<void *>(scroll),
                     static_cast<void *>(viewport),
                     viewport != nullptr ? viewport->metaObject()->className()
                                         : "(null)",
                     viewport != nullptr
                         ? viewport->objectName().toUtf8().constData() : "",
                     viewport != nullptr && viewport->isVisible() ? 1 : 0,
                     viewport != nullptr ? int(viewport->focusPolicy()) : -1,
                     viewport != nullptr &&
                         viewport->testAttribute(Qt::WA_InputMethodEnabled)
                         ? 1 : 0);
        }

        if (className == "hanul::DocumentTabImpl")
            m11LogClassMetaObject(widget);
    }

    const QObjectList objects = topLevel->findChildren<QObject *>();
    for (QObject *object : objects) {
        if (object == nullptr || object->isWidgetType())
            continue;
        const QByteArray className(object->metaObject()->className());
        const QByteArray objectName = object->objectName().toUtf8();
        if (!m11InterestingObjectName(className, objectName))
            continue;
        QObject *parent = object->parent();
        qWarning("HRT M11 INVENTORY: object=%p class=%s name=%s parent=%p parent-class=%s children=%d thread=%p",
                 static_cast<void *>(object), className.constData(),
                 objectName.constData(), static_cast<void *>(parent),
                 parent != nullptr ? parent->metaObject()->className()
                                   : "(null)",
                 object->children().size(),
                 static_cast<void *>(object->thread()));
    }

    const QWindowList windows = QGuiApplication::allWindows();
    for (QWindow *window : windows) {
        if (window == nullptr)
            continue;
        const QByteArray title = window->title().toUtf8();
        const QByteArray name = window->objectName().toUtf8();
        qWarning("HRT M11 INVENTORY: window=%p class=%s name=%s title=%s parent=%p geometry=%d,%d,%d,%d visible=%d active=%d type=%d",
                 static_cast<void *>(window),
                 window->metaObject()->className(), name.constData(),
                 title.constData(), static_cast<void *>(window->parent()),
                 window->geometry().x(), window->geometry().y(),
                 window->geometry().width(), window->geometry().height(),
                 window->isVisible() ? 1 : 0,
                 window->isActive() ? 1 : 0, int(window->type()));
    }

    qWarning("HRT M11 INVENTORY: dump-object-tree-begin");
    topLevel->dumpObjectTree();
    qWarning("HRT M11 INVENTORY: dump-object-tree-end");
}

static bool m11IsContainerWidget(QWidget *widget)
'''
    text = replace_once(text, helper_anchor, helpers,
                        "M11 document inventory helper insertion")

    call_anchor = '''    g_m11FocusRepairAttempted = true;

    QWidget *target = m11BestDocumentWidget(
'''
    call_replacement = '''    g_m11FocusRepairAttempted = true;
    m11InventoryDocumentHierarchy(
        g_m11DocumentTopLevel, g_m11DocumentPoint);

    QWidget *target = m11BestDocumentWidget(
'''
    text = replace_once(text, call_anchor, call_replacement,
                        "M11 pre-focus inventory call")

    required = {
        "HRT M11 INVENTORY:": 9,
        "HRT M11 META:": 3,
        "m11InventoryDocumentHierarchy(": 2,
        "dumpObjectTree();": 1,
        "tab-widget=%p count=%d": 1,
        "stacked-widget=%p count=%d": 1,
        "scroll-area=%p viewport=%p": 1,
        "QGuiApplication::allWindows()": 1,
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
