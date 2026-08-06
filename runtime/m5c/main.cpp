#include "qoffscreenintegration.h"
#include "qhrthostcall.h"

#include <QtCore/qbytearray.h>
#include <QtCore/qdebug.h>
#include <QtCore/qstring.h>
#include <qpa/qplatformintegrationplugin.h>

QT_BEGIN_NAMESPACE

class QHrtIntegrationPlugin : public QPlatformIntegrationPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QPlatformIntegrationFactoryInterface_iid FILE "hrtmac.json")
public:
    QPlatformIntegration *create(const QString &system,
                                 const QStringList &paramList) override
    {
        if (system.compare(QLatin1String("hrtmac"),
                           Qt::CaseInsensitive) != 0) {
            return nullptr;
        }

        const QByteArray title = QByteArrayLiteral(
            "한워드 2022 Beta — Qt QPA bridge");
        const qint64 request = hrtHostCreateWindow(
            title.constData(), title.size(), 920u, 640u);
        qWarning("HRT QPA: integration AppKit request id=%lld",
                 static_cast<long long>(request));
        return QOffscreenIntegration::createOffscreenIntegration(paramList);
    }
};

QT_END_NAMESPACE

#include "main.moc"
