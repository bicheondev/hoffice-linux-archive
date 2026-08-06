TARGET = qhrtmac
QT += core-private gui-private eventdispatcher_support-private fontdatabase_support-private

qtConfig(freetype): QMAKE_USE += freetype

SOURCES = \
    main.cpp \
    qoffscreenintegration.cpp \
    qoffscreenintegration_dummy.cpp \
    qoffscreencommon.cpp \
    qoffscreenwindow.cpp

HEADERS = \
    qhrthostcall.h \
    qoffscreenintegration.h \
    qoffscreencommon.h \
    qoffscreenwindow.h

OTHER_FILES += hrtmac.json

PLUGIN_CLASS_NAME = QHrtIntegrationPlugin
PLUGIN_TYPE = platforms
PLUGIN_EXTENDS = -

load(qt_plugin)
