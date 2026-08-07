#ifndef QHRTAPPKITBACKINGSTORE_H
#define QHRTAPPKITBACKINGSTORE_H

#include "qoffscreencommon.h"

#include <QtCore/qglobal.h>

QT_BEGIN_NAMESPACE

class QHrtAppKitBackingStore : public QOffscreenBackingStore
{
public:
    explicit QHrtAppKitBackingStore(QWindow *window);

    void flush(QWindow *window,
               const QRegion &region,
               const QPoint &offset) override;

private:
    quint64 m_presentSequence;
    bool m_firstFrameAccepted;
};

QT_END_NAMESPACE

#endif
