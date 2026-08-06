TEMPLATE = lib
TARGET = qhrtappkit
CONFIG += plugin c++11
CONFIG -= app_bundle

QT += core-private gui-private eventdispatcher_support-private fontdatabase_support-private
# The bundled HOffice QtGui omits QPlatformIntegration's Vulkan virtual slot.
# A command-line QT_NO_VULKAN alone is insufficient because Debian's generated
# qconfig.h still reports QT_FEATURE_vulkan=1.  Preinclude the compatibility
# header so qconfig is guarded and the private QPA headers see the HOffice
# feature layout from their first parse.
DEFINES += QT_NO_FOREACH
QMAKE_CXXFLAGS += -include $$PWD/hrt_qt_feature_compat.h
INCLUDEPATH += $$QTOFFSCREEN_DIR

# The archived Debian Buster runtime packages expose the versioned libraries
# used by Qt's private font database module but omit the unversioned linker
# aliases unless the separate development packages are installed.  Keep the
# ABI locked to the exact runtime SONAMEs and provide only local build aliases.
HRT_COMPAT_LIBDIR = $$OUT_PWD/compat-libs
system(mkdir -p $$HRT_COMPAT_LIBDIR)
system(ln -sf /usr/lib/x86_64-linux-gnu/libfontconfig.so.1 $$HRT_COMPAT_LIBDIR/libfontconfig.so)
system(ln -sf /usr/lib/x86_64-linux-gnu/libfreetype.so.6 $$HRT_COMPAT_LIBDIR/libfreetype.so)
QMAKE_LIBDIR += $$HRT_COMPAT_LIBDIR

SOURCES += $$PWD/main.cpp
SOURCES += $$PWD/qhrtappkitintegration.cpp
SOURCES += $$PWD/qhrtappkitwindow.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenintegration.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenintegration_dummy.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenwindow.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreencommon.cpp

HEADERS += $$PWD/hrt_qt_feature_compat.h
HEADERS += $$PWD/hrt_hostcall.h
HEADERS += $$PWD/qhrtappkitintegration.h
HEADERS += $$PWD/qhrtappkitwindow.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreenintegration.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreenwindow.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreencommon.h

OTHER_FILES += $$PWD/hrtappkit.json
DESTDIR = $$OUT_PWD/out
