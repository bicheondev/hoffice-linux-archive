#ifndef QHRTAPPKITBACKINGSTORE_H
#define QHRTAPPKITBACKINGSTORE_H

#include "qoffscreencommon.h"

#include <QtCore/qglobal.h>

QT_BEGIN_NAMESPACE

// M11 diagnostic builds add delayed editor-focus repair in the generated
// backing-store source; the stable class ABI remains unchanged here.  This
// revision retries the complete fail-closed generator and type include audit.
class QHrtAppKitBackingStore : public QOffscreenBackingStore
{
public:
    explicit QHrtAppKitBackingStore(QWindow *window);

    void flush(QWindow *window,
               const QRegion &region,
               const QPoint &offset) override;

private:
    void drainHostInput(QWindow *deliveryWindow);

    quint64 m_presentSequence;
    quint64 m_keyEventsDelivered;
    quint64 m_mouseEventsDelivered;
    bool m_firstFrameAccepted;
};

QT_END_NAMESPACE

#endif
