#ifndef QHRTHOSTCALL_H
#define QHRTHOSTCALL_H

#include <QtCore/qglobal.h>

#define HRT_HOST_CREATE_WINDOW Q_UINT64_C(0x7ff00001)

static inline qint64 hrtHostCreateWindow(const char *title,
                                         qsizetype titleLength,
                                         quint32 width,
                                         quint32 height)
{
#if defined(Q_PROCESSOR_X86_64)
    register qint64 argument4 __asm__("r10") = (qint64)height;
    qint64 result;
    __asm__ volatile(
        "syscall"
        : "=a"(result)
        : "0"((qint64)HRT_HOST_CREATE_WINDOW),
          "D"((qint64)(quintptr)title),
          "S"((qint64)titleLength),
          "d"((qint64)width),
          "r"(argument4)
        : "rcx", "r11", "cc", "memory");
    return result;
#else
    Q_UNUSED(title);
    Q_UNUSED(titleLength);
    Q_UNUSED(width);
    Q_UNUSED(height);
    return -38;
#endif
}

#endif
