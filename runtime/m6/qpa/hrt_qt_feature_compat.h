#ifndef HRT_QT_FEATURE_COMPAT_H
#define HRT_QT_FEATURE_COMPAT_H

/*
 * Debian's Qt 5.11.3 development build enables Vulkan, while the QtGui
 * shipped with HOffice 11.20.0.1520+h1 omits it.  Include qconfig first and
 * then override the generated feature macro before any QPA private header is
 * parsed.  The qconfig include guard prevents a later include from restoring
 * Debian's value.
 */
#include <QtCore/qconfig.h>

#ifdef QT_FEATURE_vulkan
#undef QT_FEATURE_vulkan
#endif
#define QT_FEATURE_vulkan -1

#ifndef QT_NO_VULKAN
#define QT_NO_VULKAN 1
#endif

#endif
