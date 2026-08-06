#include "qhrtappkitintegration.h"
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

QT_END_NAMESPACE
