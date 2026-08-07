#include "qhrtappkitbackingstore.h"
#include "qhrtappkitwindow.h"
#include "hrt_hostcall.h"
#include "../../m8/input_protocol.h"

#include <QtCore/qcoreapplication.h>
#include <QtCore/qdebug.h>
#include <QtCore/qeventloop.h>
#include <QtCore/qstring.h>
#include <QtGui/qevent.h>
#include <QtGui/qguiapplication.h>
#include <QtGui/qimage.h>
#include <QtGui/qpainter.h>
#include <QtGui/qwindow.h>
#include <qpa/qwindowsysteminterface.h>

QT_BEGIN_NAMESPACE

namespace {

/*
 * Mouse delivery can synchronously repaint HWord.  That repaint re-enters
 * flush(), which used to drain the host queue recursively before the outer
 * mouse-up had completed.  The resulting order was down → nested key → up,
 * so the text reached Qt before the click could establish focus.  All Qt GUI
 * work here is single-threaded; a process-local RAII guard therefore defers a
 * nested drain while preserving the already-enqueued FIFO order for the outer
 * loop.
 */
static bool g_m10InputDrainActive = false;

class M10InputDrainGuard
{
public:
    M10InputDrainGuard()
        : m_acquired(!g_m10InputDrainActive)
    {
        if (m_acquired)
            g_m10InputDrainActive = true;
    }

    ~M10InputDrainGuard()
    {
        if (m_acquired)
            g_m10InputDrainActive = false;
    }

    bool acquired() const { return m_acquired; }

private:
    bool m_acquired;
};

} // namespace

static Qt::KeyboardModifiers m8Modifiers(quint32 value)
{
    Qt::KeyboardModifiers result = Qt::NoModifier;
    if ((value & HRT_M8_MOD_SHIFT) != 0u) result |= Qt::ShiftModifier;
    if ((value & HRT_M8_MOD_CONTROL) != 0u) result |= Qt::ControlModifier;
    if ((value & HRT_M8_MOD_ALT) != 0u) result |= Qt::AltModifier;
    if ((value & HRT_M8_MOD_META) != 0u) result |= Qt::MetaModifier;
    return result;
}

static Qt::MouseButton m8Button(quint32 value)
{
    if ((value & HRT_M8_BUTTON_LEFT) != 0u) return Qt::LeftButton;
    if ((value & HRT_M8_BUTTON_RIGHT) != 0u) return Qt::RightButton;
    if ((value & HRT_M8_BUTTON_MIDDLE) != 0u) return Qt::MiddleButton;
    if ((value & HRT_M8_BUTTON_X1) != 0u) return Qt::XButton1;
    if ((value & HRT_M8_BUTTON_X2) != 0u) return Qt::XButton2;
    return Qt::NoButton;
}

static Qt::MouseButtons m8Buttons(quint32 value)
{
    Qt::MouseButtons result = Qt::NoButton;
    if ((value & HRT_M8_BUTTON_LEFT) != 0u) result |= Qt::LeftButton;
    if ((value & HRT_M8_BUTTON_RIGHT) != 0u) result |= Qt::RightButton;
    if ((value & HRT_M8_BUTTON_MIDDLE) != 0u) result |= Qt::MiddleButton;
    if ((value & HRT_M8_BUTTON_X1) != 0u) result |= Qt::XButton1;
    if ((value & HRT_M8_BUTTON_X2) != 0u) result |= Qt::XButton2;
    return result;
}

static void m10ActivateDeliveryWindow(QWindow *deliveryWindow,
                                      const char *phase)
{
    if (deliveryWindow == nullptr)
        return;

    QWindow *before = QGuiApplication::focusWindow();
    if (before != deliveryWindow) {
        QWindowSystemInterface::handleWindowActivated<
            QWindowSystemInterface::SynchronousDelivery>(
                deliveryWindow, Qt::ActiveWindowFocusReason);
    }
    QWindow *after = QGuiApplication::focusWindow();
    QObject *focusObject = QGuiApplication::focusObject();
    const char *focusClass = focusObject != nullptr
        ? focusObject->metaObject()->className() : "(null)";
    const QByteArray focusName = focusObject != nullptr
        ? focusObject->objectName().toUtf8() : QByteArray();
    const QByteArray title = deliveryWindow->title().toUtf8();
    qWarning("HRT M10 QPA: activation phase=%s target=%p before=%p after=%p focus-object=%p focus-class=%s focus-name=%s active=%d visible=%d title=%s",
             phase,
             static_cast<void *>(deliveryWindow),
             static_cast<void *>(before),
             static_cast<void *>(after),
             static_cast<void *>(focusObject),
             focusClass,
             focusName.constData(),
             deliveryWindow->isActive() ? 1 : 0,
             deliveryWindow->isVisible() ? 1 : 0,
             title.constData());
}

static bool m10DeliverKeyToFocusObject(QEvent::Type type,
                                       int key,
                                       Qt::KeyboardModifiers modifiers,
                                       const QString &text)
{
    QObject *receiver = QGuiApplication::focusObject();
    if (receiver == nullptr) {
        qWarning("HRT M10 QPA: direct key fallback skipped: no focus object");
        return false;
    }

    QKeyEvent directEvent(type, key, modifiers, text, false, 1u);
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
}

QHrtAppKitBackingStore::QHrtAppKitBackingStore(QWindow *window)
    : QOffscreenBackingStore(window)
    , m_presentSequence(0)
    , m_keyEventsDelivered(0)
    , m_mouseEventsDelivered(0)
    , m_firstFrameAccepted(false)
{
    qWarning("HRT M7 QPA: backing store constructed");
}

void QHrtAppKitBackingStore::drainHostInput(QWindow *deliveryWindow)
{
    if (deliveryWindow == nullptr)
        return;

    M10InputDrainGuard drainGuard;
    if (!drainGuard.acquired()) {
        qWarning("HRT M10 QPA: nested input drain deferred");
        return;
    }

    m10ActivateDeliveryWindow(deliveryWindow, "drain-begin");

    bool delivered = false;
    for (quint32 iteration = 0u; iteration < 64u; ++iteration) {
        HrtM8InputEvent event = {};
        const qint64 poll = hrtM6HostCall(
            HRT_M8_OP_POLL_INPUT,
            quint64(quintptr(&event)),
            quint64(sizeof(event)));
        if (poll == 0) {
            if (delivered) {
                qWarning("HRT M8 QPA: input queue drained key=%llu mouse=%llu",
                         static_cast<unsigned long long>(m_keyEventsDelivered),
                         static_cast<unsigned long long>(m_mouseEventsDelivered));
            }
            return;
        }
        if (poll != 1) {
            qWarning("HRT M8 QPA: input poll failed result=%lld iteration=%u",
                     static_cast<long long>(poll), iteration);
            return;
        }
        if (event.size != sizeof(HrtM8InputEvent)) {
            qWarning("HRT M8 QPA: rejected input ABI size=%u expected=%u",
                     event.size, unsigned(sizeof(HrtM8InputEvent)));
            return;
        }

        const Qt::KeyboardModifiers modifiers = m8Modifiers(event.modifiers);
        if (event.type == HRT_M8_EVENT_KEY) {
            QEvent::Type type;
            if (event.action == HRT_M8_KEY_ACTION_DOWN)
                type = QEvent::KeyPress;
            else if (event.action == HRT_M8_KEY_ACTION_UP)
                type = QEvent::KeyRelease;
            else
                continue;

            m10ActivateDeliveryWindow(deliveryWindow, "before-key");
            quint32 length = event.utf8_length;
            if (length > HRT_M8_INPUT_TEXT_BYTES)
                length = HRT_M8_INPUT_TEXT_BYTES;
            const QString text = QString::fromUtf8(event.utf8, int(length));
            const bool windowAccepted =
                QWindowSystemInterface::handleKeyEvent<
                    QWindowSystemInterface::SynchronousDelivery>(
                        deliveryWindow, type, int(event.logical_key),
                        modifiers, text, false, 1u);
            const bool directAccepted = !windowAccepted
                ? m10DeliverKeyToFocusObject(
                      type, int(event.logical_key), modifiers, text)
                : false;
            const bool accepted = windowAccepted || directAccepted;
            QCoreApplication::processEvents(QEventLoop::AllEvents, 2);
            ++m_keyEventsDelivered;
            delivered = true;
            QObject *focusObject = QGuiApplication::focusObject();
            const char *focusClass = focusObject != nullptr
                ? focusObject->metaObject()->className() : "(null)";
            qWarning("HRT M8 QPA: key event delivered sequence=%llu action=%u key=0x%x native=%u text=%s accepted=%d window-accepted=%d direct-accepted=%d focus-window=%p focus-object=%p focus-class=%s",
                     static_cast<unsigned long long>(event.sequence),
                     event.action, event.logical_key, event.native_key,
                     text.toUtf8().constData(), accepted ? 1 : 0,
                     windowAccepted ? 1 : 0, directAccepted ? 1 : 0,
                     static_cast<void *>(QGuiApplication::focusWindow()),
                     static_cast<void *>(focusObject), focusClass);
            continue;
        }

        if (event.type == HRT_M8_EVENT_MOUSE) {
            QEvent::Type type;
            Qt::MouseButton changed = Qt::NoButton;
            if (event.action == HRT_M8_MOUSE_MOVE ||
                event.action == HRT_M8_MOUSE_DRAG) {
                type = QEvent::MouseMove;
            } else if (event.action == HRT_M8_MOUSE_DOWN) {
                type = QEvent::MouseButtonPress;
                changed = m8Button(event.button);
            } else if (event.action == HRT_M8_MOUSE_UP) {
                type = QEvent::MouseButtonRelease;
                changed = m8Button(event.button);
            } else {
                continue;
            }

            m10ActivateDeliveryWindow(deliveryWindow, "before-mouse");
            const QPointF local(qreal(event.x), qreal(event.y));
            const QPointF global(qreal(event.global_x), qreal(event.global_y));
            QWindowSystemInterface::handleMouseEvent<
                QWindowSystemInterface::SynchronousDelivery>(
                    deliveryWindow, local, global,
                    m8Buttons(event.buttons), changed, type, modifiers,
                    Qt::MouseEventNotSynthesized);
            if (event.action == HRT_M8_MOUSE_UP) {
                QCoreApplication::processEvents(QEventLoop::AllEvents, 2);
                m10ActivateDeliveryWindow(deliveryWindow, "after-mouse-up");
            }
            ++m_mouseEventsDelivered;
            delivered = true;
            QObject *focusObject = QGuiApplication::focusObject();
            const char *focusClass = focusObject != nullptr
                ? focusObject->metaObject()->className() : "(null)";
            qWarning("HRT M8 QPA: mouse event delivered sequence=%llu action=%u button=0x%x buttons=0x%x local=%d,%d global=%d,%d focus-window=%p focus-object=%p focus-class=%s",
                     static_cast<unsigned long long>(event.sequence),
                     event.action, event.button, event.buttons,
                     event.x, event.y, event.global_x, event.global_y,
                     static_cast<void *>(QGuiApplication::focusWindow()),
                     static_cast<void *>(focusObject), focusClass);
        }
    }

    qWarning("HRT M8 QPA: input drain iteration limit reached key=%llu mouse=%llu",
             static_cast<unsigned long long>(m_keyEventsDelivered),
             static_cast<unsigned long long>(m_mouseEventsDelivered));
}

void QHrtAppKitBackingStore::flush(QWindow *target,
                                   const QRegion &region,
                                   const QPoint &offset)
{
    QOffscreenBackingStore::flush(target, region, offset);

    QWindow *topLevel = window();
    const qint64 hostWindow = QHrtAppKitWindow::hostWindowFor(topLevel);
    if (hostWindow <= 0)
        return;

    QPaintDevice *device = paintDevice();
    QImage *source = static_cast<QImage *>(device);
    if (source == nullptr || source->isNull() ||
        source->width() <= 0 || source->height() <= 0) {
        return;
    }

    const QImage frame =
        source->convertToFormat(QImage::Format_ARGB32_Premultiplied);
    if (frame.isNull() || frame.constBits() == nullptr ||
        frame.bytesPerLine() <= 0) {
        return;
    }

    ++m_presentSequence;
    const qint64 result = hrtM6HostCall(
        HRT_M6_OP_PRESENT_BGRA,
        quint64(quintptr(frame.constBits())),
        quint64(frame.width()),
        quint64(frame.height()),
        quint64(frame.bytesPerLine()),
        quint64(hostWindow));

    if (result <= 0) {
        if (m_presentSequence <= 8u) {
            qWarning("HRT M7 QPA: PRESENT_BGRA failed sequence=%llu result=%lld size=%dx%d stride=%d host=%lld",
                     static_cast<unsigned long long>(m_presentSequence),
                     static_cast<long long>(result),
                     frame.width(), frame.height(), frame.bytesPerLine(),
                     static_cast<long long>(hostWindow));
        }
        return;
    }

    drainHostInput(target != nullptr ? target : topLevel);

    if (!m_firstFrameAccepted) {
        const qint64 pump = hrtM6HostCall(HRT_M6_OP_PUMP_EVENTS, 50);
        const qint64 flags = hrtM6HostCall(
            HRT_M6_OP_QUERY_WINDOW, quint64(hostWindow));
        const qint64 capture = hrtM6HostCall(
            HRT_M6_OP_CAPTURE_WINDOW, quint64(hostWindow));
        const quint64 required =
            HRT_M6_WINDOW_ALLOCATED |
            HRT_M6_WINDOW_VISIBLE |
            HRT_M6_WINDOW_SERVER_LISTED |
            HRT_M6_SCREEN_AVAILABLE |
            HRT_M6_ON_MAIN_THREAD |
            HRT_M7_FRAME_PRESENTED;
        if ((quint64(flags) & required) == required && capture == 1) {
            m_firstFrameAccepted = true;
            qWarning("HRT M7 QPA: BGRA frame accepted sequence=%llu size=%dx%d stride=%d host=%lld pump=%lld flags=0x%llx capture=%lld",
                     static_cast<unsigned long long>(m_presentSequence),
                     frame.width(), frame.height(), frame.bytesPerLine(),
                     static_cast<long long>(hostWindow),
                     static_cast<long long>(pump),
                     static_cast<unsigned long long>(flags),
                     static_cast<long long>(capture));
        } else {
            qWarning("HRT M7 QPA: BGRA frame gate incomplete sequence=%llu result=%lld flags=0x%llx capture=%lld",
                     static_cast<unsigned long long>(m_presentSequence),
                     static_cast<long long>(result),
                     static_cast<unsigned long long>(flags),
                     static_cast<long long>(capture));
        }
    }
}

QT_END_NAMESPACE
