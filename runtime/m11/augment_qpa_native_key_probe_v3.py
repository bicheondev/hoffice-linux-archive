#!/usr/bin/env python3
"""Require a credible HWord editor receiver before crediting native keys.

The first Linux-native key replay was accepted by ``QTabBar``.  That proves the
extended Qt key metadata is well formed, but it is not evidence that HWord's
text editor accepted a character.  The document frame was still materializing
and the bounded wait had only been installed in the rejected-key fallback, so
it never ran once QTabBar accepted the window-system event.

This final fail-closed pass runs the reviewed v2 generator and then:

* waits for ``hword::HwordAppView`` before the window-system key path;
* explicitly prefers that editor as the repaired focus target;
* treats tab bars, document containers and other chrome as non-text receivers;
* records raw Qt acceptance separately from credible editor acceptance; and
* runs the direct fallback only against a credible editor receiver.

The 88-byte host transport ABI and all mouse behavior remain unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


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

    generator = Path(__file__).with_name(
        "augment_qpa_native_key_probe_v2.py"
    )
    if not generator.is_file():
        raise SystemExit(f"native-key v2 generator not found: {generator}")

    with tempfile.TemporaryDirectory(prefix="hrt-m11-keyroute-v3-") as temporary:
        intermediate = Path(temporary) / "native-key-v2.cpp"
        subprocess.run(
            [
                sys.executable,
                str(generator),
                str(args.source),
                str(intermediate),
            ],
            check=True,
        )
        text = intermediate.read_text(encoding="utf-8")

    if "credible-accepted=" in text:
        raise SystemExit("credible HWord native key routing is already present")

    helper_anchor = '''static void m11LinuxNativeKeyFields(int key, quint32 hostNative,
                                    quint32 *scanCode,
'''
    helpers = r'''static bool m11CredibleTextReceiver(QObject *receiver)
{
    if (receiver == nullptr)
        return false;
    const QByteArray className(receiver->metaObject()->className());
    const QByteArray lowerClass = className.toLower();
    if (className == "hword::HwordAppView")
        return true;
    if (lowerClass.contains("editor") || lowerClass.contains("canvas") ||
        lowerClass.contains("textedit") || lowerClass.contains("lineedit") ||
        lowerClass.contains("plaintextedit")) {
        return true;
    }
    return false;
}

static QWidget *m11FindCredibleEditorWidget(QWidget *topLevel)
{
    if (topLevel == nullptr)
        return nullptr;
    if (topLevel->isWidgetType() && m11CredibleTextReceiver(topLevel))
        return topLevel;
    const QWidgetList widgets = topLevel->findChildren<QWidget *>();
    for (QWidget *widget : widgets) {
        if (widget != nullptr && widget->isVisible() && widget->isEnabled() &&
            m11CredibleTextReceiver(widget)) {
            return widget;
        }
    }
    return nullptr;
}

static void m11LinuxNativeKeyFields(int key, quint32 hostNative,
                                    quint32 *scanCode,
'''
    text = replace_once(text, helper_anchor, helpers,
                        "credible editor helper insertion")

    timeout_anchor = '''    while (timer.elapsed() < 1500) {
'''
    timeout_replacement = '''    while (timer.elapsed() < 3500) {
'''
    text = replace_once(text, timeout_anchor, timeout_replacement,
                        "document materialization timeout")

    readiness_anchor = '''        QWidget *document = m11FindDocumentTab(topLevel);
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
'''
    readiness_replacement = '''        QWidget *editor = m11FindCredibleEditorWidget(topLevel);
        if (editor != nullptr) {
            materialized = true;
            qWarning("HRT M11 KEYROUTE: credible editor materialized editor=%p class=%s elapsed-ms=%lld",
                     static_cast<void *>(editor),
                     editor->metaObject()->className(),
                     static_cast<long long>(timer.elapsed()));
        } else {
            QWidget *document = m11FindDocumentTab(topLevel);
            if (document != nullptr) {
                const QList<QTabWidget *> tabs =
                    document->findChildren<QTabWidget *>();
                for (QTabWidget *tab : tabs) {
                    if (tab != nullptr && tab->count() > 0 &&
                        tab->currentWidget() != nullptr) {
                        qWarning("HRT M11 KEYROUTE: document page exists without a credible editor tab=%p count=%d current=%p current-class=%s elapsed-ms=%lld",
                                 static_cast<void *>(tab), tab->count(),
                                 static_cast<void *>(tab->currentWidget()),
                                 tab->currentWidget()->metaObject()->className(),
                                 static_cast<long long>(timer.elapsed()));
                        break;
                    }
                }
            }
        }
'''
    text = replace_once(text, readiness_anchor, readiness_replacement,
                        "credible editor readiness")

    target_anchor = '''    QWidget *target = m11BestDocumentWidget(
        g_m11DocumentTopLevel, g_m11DocumentPoint);
'''
    target_replacement = '''    QWidget *target = m11FindCredibleEditorWidget(
        g_m11DocumentTopLevel);
    if (target != nullptr) {
        qWarning("HRT M11 KEYROUTE: focus repair prefers credible editor target=%p class=%s",
                 static_cast<void *>(target),
                 target->metaObject()->className());
    } else {
        target = m11BestDocumentWidget(
            g_m11DocumentTopLevel, g_m11DocumentPoint);
    }
'''
    text = replace_once(text, target_anchor, target_replacement,
                        "credible editor focus preference")

    direct_anchor = '''    if (focusWidget != nullptr)
        m10LogWidget("key-target", focusWidget, QPoint(-1, -1));

    quint32 nativeScanCode = 0u;
'''
    direct_replacement = '''    if (focusWidget != nullptr)
        m10LogWidget("key-target", focusWidget, QPoint(-1, -1));
    if (!m11CredibleTextReceiver(receiver)) {
        qWarning("HRT M11 KEYROUTE: direct key skipped non-editor receiver=%p class=%s",
                 static_cast<void *>(receiver),
                 receiver->metaObject()->className());
        return false;
    }

    quint32 nativeScanCode = 0u;
'''
    text = replace_once(text, direct_anchor, direct_replacement,
                        "direct non-editor rejection")

    prepare_anchor = '''            m10ActivateDeliveryWindow(deliveryWindow, "before-key");
            quint32 length = event.utf8_length;
'''
    prepare_replacement = '''            m10ActivateDeliveryWindow(deliveryWindow, "before-key");
            QWidget *preparedFocus = m10DirectWidgetInputEnabled()
                ? QApplication::focusWidget() : nullptr;
            if (m10DirectWidgetInputEnabled())
                preparedFocus = m11RepairDocumentFocus(preparedFocus);
            QObject *preparedObject = preparedFocus != nullptr
                ? static_cast<QObject *>(preparedFocus)
                : QGuiApplication::focusObject();
            qWarning("HRT M11 KEYROUTE: prepared focus receiver=%p class=%s credible=%d",
                     static_cast<void *>(preparedObject),
                     preparedObject != nullptr
                         ? preparedObject->metaObject()->className() : "(null)",
                     m11CredibleTextReceiver(preparedObject) ? 1 : 0);
            quint32 length = event.utf8_length;
'''
    text = replace_once(text, prepare_anchor, prepare_replacement,
                        "pre-window editor preparation")

    window_anchor = '''            const bool windowAccepted =
                QWindowSystemInterface::handleExtendedKeyEvent(
                    deliveryWindow, type, int(event.logical_key),
                    modifiers, nativeScanCode, nativeVirtualKey,
                    nativeModifiers, text, false, 1u, true);
            qWarning("HRT M11 KEYROUTE: extended window key type=%d key=0x%x host-native=%u scan=%u virtual=0x%x native-modifiers=0x%x accepted=%d",
                     int(type), event.logical_key, event.native_key,
                     nativeScanCode, nativeVirtualKey, nativeModifiers,
                     windowAccepted ? 1 : 0);
            const bool directAccepted = !windowAccepted
'''
    window_replacement = '''            const bool rawWindowAccepted =
                QWindowSystemInterface::handleExtendedKeyEvent(
                    deliveryWindow, type, int(event.logical_key),
                    modifiers, nativeScanCode, nativeVirtualKey,
                    nativeModifiers, text, false, 1u, true);
            QObject *windowReceiver = QGuiApplication::focusObject();
            const bool windowAccepted = rawWindowAccepted &&
                m11CredibleTextReceiver(windowReceiver);
            qWarning("HRT M11 KEYROUTE: extended window key type=%d key=0x%x host-native=%u scan=%u virtual=0x%x native-modifiers=0x%x raw-accepted=%d credible-accepted=%d receiver=%p receiver-class=%s",
                     int(type), event.logical_key, event.native_key,
                     nativeScanCode, nativeVirtualKey, nativeModifiers,
                     rawWindowAccepted ? 1 : 0,
                     windowAccepted ? 1 : 0,
                     static_cast<void *>(windowReceiver),
                     windowReceiver != nullptr
                         ? windowReceiver->metaObject()->className() : "(null)");
            const bool directAccepted = !windowAccepted
'''
    text = replace_once(text, window_anchor, window_replacement,
                        "credible window acceptance")

    required = {
        "m11CredibleTextReceiver(": 7,
        "m11FindCredibleEditorWidget(": 4,
        "credible editor materialized": 1,
        "focus repair prefers credible editor": 1,
        "direct key skipped non-editor": 1,
        "prepared focus receiver=": 1,
        "raw-accepted=%d credible-accepted=%d": 1,
        "timer.elapsed() < 3500": 1,
        "timer.elapsed() < 1500": 0,
        "const bool rawWindowAccepted": 1,
        "const bool windowAccepted = rawWindowAccepted": 1,
        "augment_qpa_native_key_probe_v2.py": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"native-key-v3 marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
