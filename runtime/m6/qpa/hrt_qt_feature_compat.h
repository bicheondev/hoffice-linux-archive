#ifndef HRT_QT_FEATURE_COMPAT_H
#define HRT_QT_FEATURE_COMPAT_H

/*
 * Debian's Qt 5.11.3 development build enables Vulkan, while the QtGui
 * shipped with HOffice 11.20.0.1520+h1 omits it.  qmake also preincludes this
 * file while generating moc_predefs.h, before it adds Qt's normal -isystem
 * include paths.  The multiarch fallback therefore has to be reachable from
 * the compiler's default /usr/include search path as well.
 */
#if defined(__has_include)
#  if __has_include(<QtCore/qconfig.h>)
#    include <QtCore/qconfig.h>
#  elif __has_include(<x86_64-linux-gnu/qt5/QtCore/qconfig.h>)
#    include <x86_64-linux-gnu/qt5/QtCore/qconfig.h>
#  else
#    error "Qt 5 qconfig.h was not found"
#  endif
#else
#  include <x86_64-linux-gnu/qt5/QtCore/qconfig.h>
#endif

#ifdef QT_FEATURE_vulkan
#  undef QT_FEATURE_vulkan
#endif
#define QT_FEATURE_vulkan -1

#ifndef QT_NO_VULKAN
#  define QT_NO_VULKAN 1
#endif

#endif
