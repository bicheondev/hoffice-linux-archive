#ifndef QHRTAPPKITWINDOW_H
#define QHRTAPPKITWINDOW_H

#include "qoffscreenwindow.h"

#include <QtCore/qglobal.h>

QT_BEGIN_NAMESPACE

class QHrtAppKitWindow : public QOffscreenWindow
{
public:
    explicit QHrtAppKitWindow(QWindow *window);
    ~QHrtAppKitWindow() override;

    void setVisible(bool visible) override;
    void setGeometry(const QRect &rect) override;
    void setWindowTitle(const QString &title) override;
    void requestActivateWindow() override;

    static qint64 hostWindowFor(const QWindow *window);

private:
    bool isNativeCandidate() const;
    void createNativeWindow();
    void destroyNativeWindow();
    void unregisterWindow();

    qint64 m_hostWindow;
    bool m_visible;
    QHrtAppKitWindow *m_nextWindow;

    static QHrtAppKitWindow *s_windows;
};

QT_END_NAMESPACE

#endif
