#include "qhrtappkitwindow.h"
#include "hrt_hostcall.h"

#include <QtCore/qbytearray.h>
#include <QtCore/qdebug.h>
#include <QtGui/qwindow.h>

QT_BEGIN_NAMESPACE

QHrtAppKitWindow *QHrtAppKitWindow::s_nativeOwner = nullptr;

QHrtAppKitWindow::QHrtAppKitWindow(QWindow *window)
    : QOffscreenWindow(window)
    , m_hostWindow(0)
    , m_visible(false)
{
    const QByteArray title = window->title().toUtf8();
    qWarning("HRT M6 QPA: QPlatformWindow constructed type=%d title=%s",
             int(window->type()), title.constData());
}

QHrtAppKitWindow::~QHrtAppKitWindow()
{
    destroyNativeWindow();
}

qint64 QHrtAppKitWindow::hostWindowFor(const QWindow *candidate)
{
    if (candidate == nullptr || s_nativeOwner == nullptr ||
        s_nativeOwner->m_hostWindow <= 0 ||
        s_nativeOwner->window() != candidate) {
        return 0;
    }
    return s_nativeOwner->m_hostWindow;
}

bool QHrtAppKitWindow::isNativeCandidate() const
{
    const Qt::WindowType type = window()->type();
    return type != Qt::ToolTip &&
           type != Qt::Popup &&
           type != Qt::Desktop;
}

void QHrtAppKitWindow::createNativeWindow()
{
    if (m_hostWindow > 0 || s_nativeOwner != nullptr ||
        !m_visible || !isNativeCandidate()) {
        return;
    }

    QByteArray title = window()->title().toUtf8();
    if (title.isEmpty())
        title = QByteArrayLiteral("HWord Qt Window");
    if (title.size() > 255)
        title.truncate(255);

    const QRect rect = geometry();
    const qint64 handle = hrtM6HostCall(
        HRT_M6_OP_CREATE_WINDOW,
        quint64(quintptr(title.constData())),
        quint64(qMax(1, rect.width())),
        quint64(qMax(1, rect.height())));
    if (handle <= 0) {
        qWarning("HRT M6 QPA: CREATE failed type=%d result=%lld title=%s",
                 int(window()->type()), static_cast<long long>(handle),
                 title.constData());
        return;
    }

    m_hostWindow = handle;
    s_nativeOwner = this;
    const qint64 pump = hrtM6HostCall(HRT_M6_OP_PUMP_EVENTS, 250);
    const qint64 flags = hrtM6HostCall(
        HRT_M6_OP_QUERY_WINDOW, quint64(handle));
    const qint64 capture = hrtM6HostCall(
        HRT_M6_OP_CAPTURE_WINDOW, quint64(handle));
    qWarning("HRT M6 QPA: CREATE type=%d geometry=%dx%d title=%s handle=%lld pump=%lld flags=0x%llx capture=%lld",
             int(window()->type()), rect.width(), rect.height(),
             title.constData(), static_cast<long long>(handle),
             static_cast<long long>(pump),
             static_cast<unsigned long long>(flags),
             static_cast<long long>(capture));
}

void QHrtAppKitWindow::destroyNativeWindow()
{
    if (m_hostWindow <= 0)
        return;

    const qint64 handle = m_hostWindow;
    const qint64 result = hrtM6HostCall(
        HRT_M6_OP_DESTROY_WINDOW, quint64(handle));
    qWarning("HRT M6 QPA: DESTROY handle=%lld result=%lld",
             static_cast<long long>(handle),
             static_cast<long long>(result));
    m_hostWindow = 0;
    if (s_nativeOwner == this)
        s_nativeOwner = nullptr;
}

void QHrtAppKitWindow::setVisible(bool visible)
{
    QOffscreenWindow::setVisible(visible);
    m_visible = visible;
    if (visible)
        createNativeWindow();
    else
        destroyNativeWindow();
}

void QHrtAppKitWindow::setGeometry(const QRect &rect)
{
    QOffscreenWindow::setGeometry(rect);
    if (m_hostWindow > 0) {
        qWarning("HRT M6 QPA: GEOMETRY handle=%lld rect=%d,%d %dx%d",
                 static_cast<long long>(m_hostWindow),
                 rect.x(), rect.y(), rect.width(), rect.height());
    }
}

void QHrtAppKitWindow::setWindowTitle(const QString &title)
{
    QOffscreenWindow::setWindowTitle(title);
    if (m_hostWindow > 0) {
        const QByteArray utf8 = title.toUtf8();
        qWarning("HRT M6 QPA: TITLE handle=%lld title=%s",
                 static_cast<long long>(m_hostWindow), utf8.constData());
    }
}

QT_END_NAMESPACE
