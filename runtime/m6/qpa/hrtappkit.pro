TEMPLATE = lib
TARGET = qhrtappkit
CONFIG += plugin c++11
CONFIG -= app_bundle

QT += core-private gui-private widgets eventdispatcher_support-private fontdatabase_support-private
DEFINES += QT_NO_FOREACH HRT_M10_DIRECT_WIDGET_INPUT_DEFAULT=1
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

# Generate the QWidget-aware variant in three fail-closed passes.  The first
# pass adds hit testing and focus-object delivery; the second guarantees that
# the HWord New QToolButton emits its application signal and records every
# visible focus candidate beneath the document point; the third yields after
# each mouse-up so a synchronously enqueued next stage cannot overtake HWord's
# document/widget construction.
HRT_M10_WIDGET_BASE = $$OUT_PWD/qhrtappkitbackingstore_widget.cpp
HRT_M10_BUTTON_FOCUS = $$OUT_PWD/qhrtappkitbackingstore_button_focus.cpp
HRT_M11_BACKINGSTORE = $$OUT_PWD/qhrtappkitbackingstore_m11.cpp
system(python3 $$PWD/../../m10/augment_qpa_widget_input.py $$PWD/qhrtappkitbackingstore.cpp $$HRT_M10_WIDGET_BASE)
system(python3 $$PWD/../../m10/augment_qpa_button_focus.py $$HRT_M10_WIDGET_BASE $$HRT_M10_BUTTON_FOCUS)
system(python3 $$PWD/../../m11/augment_qpa_stage_boundaries.py $$HRT_M10_BUTTON_FOCUS $$HRT_M11_BACKINGSTORE)
exists($$HRT_M11_BACKINGSTORE) {
    message(Building stage-separated QWidget-aware M11 backing store: $$HRT_M11_BACKINGSTORE)
} else {
    error(Failed to generate stage-separated QWidget-aware M11 backing store)
}

SOURCES += $$PWD/main.cpp
SOURCES += $$PWD/qhrtappkitintegration.cpp
SOURCES += $$PWD/qhrtappkitwindow.cpp
SOURCES += $$HRT_M11_BACKINGSTORE
SOURCES += $$PWD/qplatform_vulkan_compat.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenintegration.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenintegration_dummy.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenwindow.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreencommon.cpp

HEADERS += $$PWD/hrt_hostcall.h
HEADERS += $$PWD/qhrtappkitintegration.h
HEADERS += $$PWD/qhrtappkitwindow.h
HEADERS += $$PWD/qhrtappkitbackingstore.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreenintegration.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreenwindow.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreencommon.h

OTHER_FILES += $$PWD/hrtappkit.json
DESTDIR = $$OUT_PWD/out
