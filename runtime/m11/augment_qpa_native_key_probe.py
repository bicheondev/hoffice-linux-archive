#!/usr/bin/env python3
"""Probe HWord's real Linux key route after document-frame creation.

The exact M11 replay now reaches a live ``hanul::DocumentTabImpl`` without a
runtime crash, but the first printable key is rejected.  Two ambiguities remain:

* the document click and key delivery are separated by only one repaint, while
  ``HwordFrameManager::CreateFrame`` is still completing; and
* the generic QPA key helper supplies zero native scan/virtual-key fields,
  unlike Qt's Linux/XCB backend.

This fail-closed final transform therefore does three diagnostic things only:

1. installs a passive application event filter for focus, shortcut, key and IME
   events;
2. pumps Qt for up to 1.5 seconds before the first key while recording tab,
   stacked-page and scrollbar materialization; and
3. uses Qt 5.11.3's ``handleExtendedKeyEvent`` plus the extended QKeyEvent
   constructor with the X11 keycode/keysym pair for ``A`` (38 / 0x61).

The host transport ABI, mouse path and non-printable key mapping are unchanged.
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
    if "HRT M11 KEYROUTE:" in text:
        raise SystemExit("M11 native key-route probe is already present")

    include_anchor = '#include <QtCore/qvariant.h>\n'
    include_replacement = (
        '#include <QtCore/qvariant.h>\n'
        '#include <QtCore/qelapsedtimer.h>\n'
        '#include <QtCore/qthread.h>\n'
    )
    text = replace_once(text, include_anchor, include_replacement,
                        "native key-route includes")

    helper_anchor = '''static bool m11IsContainerWidget(QWidget *widget)
'''
    helpers = r'''class M11KeyRouteEventFilter : public QObject
{
public:
    explicit M11KeyRouteEventFilter(QObject *parent)
        : QObject(parent)
    {
    }

protected:
    bool eventFilter(QObject *watched, QEvent *event) override
    {
        if (watched == nullptr || event == nullptr)
            return false;
        const QEvent::Type type = event->type();
        if (type != QEvent::FocusIn && type != QEvent::FocusOut &&
            type != QEvent::ShortcutOverride &&
            type != QEvent::KeyPress && type != QEvent::KeyRelease &&
            type != QEvent::InputMethod &&
            type != QEvent::InputMethodQuery) {
            return false;
        }

        const QByteArray name = watched->objectName().toUtf8();
        int key = 0;
        quint32 scan = 0u;
        quint32 virtualKey = 0u;
        quint32 nativeModifiers = 0u;
        QByteArray text;
        if (type == QEvent::ShortcutOverride ||
            type == QEvent::KeyPress || type == QEvent::KeyRelease) {
            QKeyEvent *keyEvent = static_cast<QKeyEvent *>(event);
            key = keyEvent->key();
            scan = keyEvent->nativeScanCode();
            virtualKey = keyEvent->nativeVirtualKey();
            nativeModifiers = keyEvent->nativeModifiers();
            text = keyEvent->text().toUtf8();
        }
        qWarning("HRT M11 KEYROUTE: filter receiver=%p class=%s name=%s type=%d accepted-entry=%d key=0x%x scan=%u virtual=0x%x native-modifiers=0x%x text=%s",
                 static_cast<void *>(watched),
                 watched->metaObject()->className(), name.constData(),
                 int(type), event->isAccepted() ? 1 : 0, key, scan,
                 virtualKey, nativeModifiers, text.constData());
        return false;
    }
};

static M11KeyRouteEventFilter *g_m11KeyRouteEventFilter = nullptr;
static bool g_m11MaterializationWaitCompleted = false;

static void m11InstallKeyRouteEventFilter()
{
    if (g_m11KeyRouteEventFilter != nullptr || qApp == nullptr)
        return;
    g_m11KeyRouteEventFilter = new M11KeyRouteEventFilter(qApp);
    qApp->installEventFilter(g_m11KeyRouteEventFilter);
    qWarning("HRT M11 KEYROUTE: application event filter installed");
}

static QWidget *m11FindDocumentTab(QWidget *topLevel)
{
    if (topLevel == nullptr)
        return nullptr;
    if (QByteArray(topLevel->metaObject()->className()) ==
        "hanul::DocumentTabImpl") {
        return topLevel;
    }
    const QWidgetList widgets = topLevel->findChildren<QWidget *>();
    for (QWidget *widget : widgets) {
        if (widget != nullptr &&
            QByteArray(widget->metaObject()->className()) ==
                "hanul::DocumentTabImpl") {
            return widget;
        }
    }
    return nullptr;
}

static void m11LogMaterializationState(QWidget *topLevel,
                                       qint64 elapsedMilliseconds,
                                       const char *phase)
{
    QWidget *document = m11FindDocumentTab(topLevel);
    int tabWidgets = 0;
    int tabPages = 0;
    int currentPages = 0;
    int stackedWidgets = 0;
    int stackedPages = 0;
    int scrollbarCount = 0;
    int nonEmptyScrollbars = 0;
    int widgetCount = 0;
    int objectCount = 0;
    if (document != nullptr) {
        widgetCount = document->findChildren<QWidget *>().size();
        objectCount = document->findChildren<QObject *>().size();
        const QList<QTabWidget *> tabs =
            document->findChildren<QTabWidget *>();
        tabWidgets = tabs.size();
        for (QTabWidget *tab : tabs) {
            if (tab == nullptr)
                continue;
            tabPages += tab->count();
            if (tab->currentWidget() != nullptr)
                ++currentPages;
        }
        const QList<QStackedWidget *> stacks =
            document->findChildren<QStackedWidget *>();
        stackedWidgets = stacks.size();
        for (QStackedWidget *stack : stacks) {
            if (stack != nullptr)
                stackedPages += stack->count();
        }
        const QList<QScrollBar *> scrollbars =
            document->findChildren<QScrollBar *>();
        scrollbarCount = scrollbars.size();
        for (QScrollBar *scrollbar : scrollbars) {
            if (scrollbar != nullptr &&
                (scrollbar->maximum() > scrollbar->minimum() ||
                 scrollbar->pageStep() > 0)) {
                ++nonEmptyScrollbars;
            }
        }
    }
    QWidget *focusWidget = QApplication::focusWidget();
    QObject *focusObject = QGuiApplication::focusObject();
    qWarning("HRT M11 KEYROUTE: materialization phase=%s elapsed-ms=%lld document=%p document-class=%s document-children=%d document-objects=%d tab-widgets=%d tab-pages=%d current-pages=%d stacked-widgets=%d stacked-pages=%d scrollbars=%d nonempty-scrollbars=%d focus-widget=%p focus-widget-class=%s focus-object=%p focus-object-class=%s",
             phase, static_cast<long long>(elapsedMilliseconds),
             static_cast<void *>(document),
             document != nullptr ? document->metaObject()->className()
                                 : "(null)",
             widgetCount, objectCount, tabWidgets, tabPages, currentPages,
             stackedWidgets, stackedPages, scrollbarCount,
             nonEmptyScrollbars, static_cast<void *>(focusWidget),
             focusWidget != nullptr ? focusWidget->metaObject()->className()
                                    : "(null)",
             static_cast<void *>(focusObject),
             focusObject != nullptr ? focusObject->metaObject()->className()
                                    : "(null)");
}

static void m11WaitForDocumentMaterialization(QWidget *topLevel)
{
    if (g_m11MaterializationWaitCompleted || topLevel == nullptr)
        return;
    g_m11MaterializationWaitCompleted = true;
    m11InstallKeyRouteEventFilter();

    QElapsedTimer timer;
    timer.start();
    qint64 nextLog = 0;
    bool materialized = false;
    while (timer.elapsed() < 1500) {
        QCoreApplication::sendPostedEvents(nullptr, 0);
        QCoreApplication::processEvents(QEventLoop::AllEvents, 25);

        QWidget *document = m11FindDocumentTab(topLevel);
        if (document != nullptr) {
            const QList<QTabWidget *> tabs =
                document->findChildren<QTabWidget *>();
            for (QTabWidget *tab : tabs) {
                if (tab != nullptr && tab->count() > 0 &&
                    tab->currentWidget() != nullptr) {
                    materialized = true;
                    break;
                }
            }
        }
        if (timer.elapsed() >= nextLog || materialized) {
            m11LogMaterializationState(
                topLevel, timer.elapsed(),
                materialized ? "ready" : "waiting");
            nextLog += 100;
        }
        if (materialized)
            break;
        QThread::msleep(5);
    }
    m11LogMaterializationState(
        topLevel, timer.elapsed(), materialized ? "final-ready" : "timeout");
}

static void m11LinuxNativeKeyFields(int key, quint32 hostNative,
                                    quint32 *scanCode,
                                    quint32 *virtualKey,
                                    quint32 *nativeModifiers)
{
    quint32 scan = hostNative;
    quint32 virtualValue = quint32(key);
    quint32 nativeValue = 0u;
    if (key == Qt::Key_A) {
        /* X11/XKB keycode 38 and XK_a keysym 0x61. */
        scan = 38u;
        virtualValue = 0x61u;
    }
    if (scanCode != nullptr)
        *scanCode = scan;
    if (virtualKey != nullptr)
        *virtualKey = virtualValue;
    if (nativeModifiers != nullptr)
        *nativeModifiers = nativeValue;
}

static bool m11IsContainerWidget(QWidget *widget)
'''
    text = replace_once(text, helper_anchor, helpers,
                        "native key-route helper insertion")

    wait_anchor = '''    m11InventoryDocumentHierarchy(
        g_m11DocumentTopLevel, g_m11DocumentPoint);

    QWidget *target = m11BestDocumentWidget(
'''
    wait_replacement = '''    m11InventoryDocumentHierarchy(
        g_m11DocumentTopLevel, g_m11DocumentPoint);
    m11WaitForDocumentMaterialization(g_m11DocumentTopLevel);

    QWidget *target = m11BestDocumentWidget(
'''
    text = replace_once(text, wait_anchor, wait_replacement,
                        "pre-key materialization wait")

    direct_anchor = '''    QKeyEvent directEvent(type, key, modifiers, text, false, 1u);
    directEvent.setAccepted(false);
'''
    direct_replacement = '''    quint32 nativeScanCode = 0u;
    quint32 nativeVirtualKey = 0u;
    quint32 nativeModifiers = 0u;
    m11LinuxNativeKeyFields(key, 0u, &nativeScanCode,
                            &nativeVirtualKey, &nativeModifiers);
    QKeyEvent directEvent(type, key, modifiers,
                          nativeScanCode, nativeVirtualKey,
                          nativeModifiers, text, false, 1u);
    directEvent.setAccepted(false);
'''
    text = replace_once(text, direct_anchor, direct_replacement,
                        "extended direct QKeyEvent")

    window_anchor = '''            const bool windowAccepted =
                QWindowSystemInterface::handleKeyEvent<
                    QWindowSystemInterface::SynchronousDelivery>(
                        deliveryWindow, type, int(event.logical_key),
                        modifiers, text, false, 1u);
'''
    window_replacement = '''            quint32 nativeScanCode = 0u;
            quint32 nativeVirtualKey = 0u;
            quint32 nativeModifiers = 0u;
            m11LinuxNativeKeyFields(
                int(event.logical_key), event.native_key,
                &nativeScanCode, &nativeVirtualKey, &nativeModifiers);
            const bool windowAccepted =
                QWindowSystemInterface::handleExtendedKeyEvent(
                    deliveryWindow, type, int(event.logical_key),
                    modifiers, nativeScanCode, nativeVirtualKey,
                    nativeModifiers, text, false, 1u, true);
            qWarning("HRT M11 KEYROUTE: extended window key type=%d key=0x%x host-native=%u scan=%u virtual=0x%x native-modifiers=0x%x accepted=%d",
                     int(type), event.logical_key, event.native_key,
                     nativeScanCode, nativeVirtualKey, nativeModifiers,
                     windowAccepted ? 1 : 0);
'''
    text = replace_once(text, window_anchor, window_replacement,
                        "extended QWindowSystemInterface key delivery")

    required = {
        "HRT M11 KEYROUTE:": 5,
        "m11WaitForDocumentMaterialization(": 2,
        "m11InstallKeyRouteEventFilter(": 2,
        "handleExtendedKeyEvent(": 1,
        "nativeScanCode, nativeVirtualKey": 2,
        "QThread::msleep(5);": 1,
        "timer.elapsed() < 1500": 1,
        "X11/XKB keycode 38": 1,
        "QKeyEvent directEvent(type, key, modifiers,": 1,
        "QWindowSystemInterface::handleKeyEvent<": 0,
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
