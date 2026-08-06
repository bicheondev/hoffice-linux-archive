TEMPLATE = lib
TARGET = qhrtappkit
CONFIG += plugin c++11
CONFIG -= app_bundle

QT += core-private gui-private eventdispatcher_support-private fontdatabase_support-private
DEFINES += QT_NO_FOREACH
INCLUDEPATH += $$QTOFFSCREEN_DIR

SOURCES += $$PWD/main.cpp
SOURCES += $$PWD/qhrtappkitintegration.cpp
SOURCES += $$PWD/qhrtappkitwindow.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenintegration.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenintegration_dummy.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreenwindow.cpp
SOURCES += $$QTOFFSCREEN_DIR/qoffscreencommon.cpp

HEADERS += $$PWD/hrt_hostcall.h
HEADERS += $$PWD/qhrtappkitintegration.h
HEADERS += $$PWD/qhrtappkitwindow.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreenintegration.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreenwindow.h
HEADERS += $$QTOFFSCREEN_DIR/qoffscreencommon.h

OTHER_FILES += $$PWD/hrtappkit.json
DESTDIR = $$OUT_PWD/out
