#include "qhrtappkitintegration.h"
#include "qhrtappkitbackingstore.h"
#include "qhrtappkitwindow.h"

#include <QtCore/qdebug.h>

QT_BEGIN_NAMESPACE

QHrtAppKitIntegration::QHrtAppKitIntegration()
    : QOffscreenIntegration()
{
    qWarning("HRT M6 QPA: integration constructed");
}

QPlatformWindow *QHrtAppKitIntegration::createPlatformWindow(QWindow *window) const
{
    QPlatformWindow *platformWindow = new QHrtAppKitWindow(window);
    platformWindow->requestActivateWindow();
    return platformWindow;
}

QPlatformBackingStore *
QHrtAppKitIntegration::createPlatformBackingStore(QWindow *window) const
{
    return new QHrtAppKitBackingStore(window);
}

QT_END_NAMESPACE
