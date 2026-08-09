#ifndef QHRTAPPKITBACKINGSTORE_H
#define QHRTAPPKITBACKINGSTORE_H

#include "qoffscreencommon.h"

#include <QtCore/qglobal.h>

QT_BEGIN_NAMESPACE

// M11 diagnostic builds generate document hierarchy inventory, delayed focus,
// composition fallback, a bounded editor-materialization wait, and Linux/X11
// native key metadata.  The stable backing-store class ABI remains unchanged;
// this revision retries the Qt 5.11.3 build after making the chained native-key
// generator independent of qmake's current working directory.
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
