#ifndef QHRTAPPKITINTEGRATION_H
#define QHRTAPPKITINTEGRATION_H

#include "qoffscreenintegration.h"

QT_BEGIN_NAMESPACE

class QHrtAppKitIntegration : public QOffscreenIntegration
{
public:
    QHrtAppKitIntegration();
    QPlatformWindow *createPlatformWindow(QWindow *window) const override;
    QPlatformBackingStore *
    createPlatformBackingStore(QWindow *window) const override;
};

QT_END_NAMESPACE

#endif
