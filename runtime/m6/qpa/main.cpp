#include <qpa/qplatformintegrationplugin.h>

#include "qhrtappkitintegration.h"

QT_BEGIN_NAMESPACE

class QHrtAppKitIntegrationPlugin : public QPlatformIntegrationPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QPlatformIntegrationFactoryInterface_iid FILE "hrtappkit.json")
public:
    QPlatformIntegration *create(const QString &system,
                                 const QStringList &parameters) override;
};

QPlatformIntegration *QHrtAppKitIntegrationPlugin::create(
    const QString &system, const QStringList &parameters)
{
    Q_UNUSED(parameters);
    if (!system.compare(QLatin1String("hrtappkit"), Qt::CaseInsensitive))
        return new QHrtAppKitIntegration;
    return nullptr;
}

QT_END_NAMESPACE

#include "main.moc"
