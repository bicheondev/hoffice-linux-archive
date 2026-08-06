#include <qpa/qplatformintegration.h>

QT_BEGIN_NAMESPACE

/*
 * Debian's Qt 5.11.3 QPA headers expose this trailing virtual because that
 * build enables Vulkan.  The QtGui bundled with HOffice 11.20.0.1520+h1 was
 * built without Vulkan and therefore does not export the implementation.
 *
 * The slot is the final virtual in QPlatformIntegration, so all preceding
 * vtable indices used by the non-Vulkan HOffice Qt build remain identical.
 * Defining the never-used trailing method inside the plugin removes the sole
 * missing Qt_5_PRIVATE_API relocation without adding or replacing any HOffice
 * functionality.
 */
QPlatformVulkanInstance *
QPlatformIntegration::createPlatformVulkanInstance(QVulkanInstance *) const
{
    return nullptr;
}

QT_END_NAMESPACE
