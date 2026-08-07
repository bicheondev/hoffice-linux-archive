#include "qhrtappkitbackingstore.h"
#include "qhrtappkitwindow.h"
#include "hrt_hostcall.h"

#include <QtCore/qdebug.h>
#include <QtGui/qimage.h>
#include <QtGui/qpainter.h>
#include <QtGui/qwindow.h>

QT_BEGIN_NAMESPACE

QHrtAppKitBackingStore::QHrtAppKitBackingStore(QWindow *window)
    : QOffscreenBackingStore(window)
    , m_presentSequence(0)
    , m_firstFrameAccepted(false)
{
    qWarning("HRT M7 QPA: backing store constructed");
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
