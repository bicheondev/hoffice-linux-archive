#ifndef QHRTAPPKITWINDOW_H
#define QHRTAPPKITWINDOW_H

#include "qoffscreenwindow.h"

QT_BEGIN_NAMESPACE

class QHrtAppKitWindow : public QOffscreenWindow
{
public:
    explicit QHrtAppKitWindow(QWindow *window);
    ~QHrtAppKitWindow() override;

    void setVisible(bool visible) override;
    void setGeometry(const QRect &rect) override;
    void setWindowTitle(const QString &title) override;

private:
    bool isNativeCandidate() const;
    void createNativeWindow();
    void destroyNativeWindow();

    qint64 m_hostWindow;
    bool m_visible;

    static QHrtAppKitWindow *s_nativeOwner;
};

QT_END_NAMESPACE

#endif
