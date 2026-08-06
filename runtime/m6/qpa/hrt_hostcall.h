#ifndef HRT_M6_QPA_HOSTCALL_H
#define HRT_M6_QPA_HOSTCALL_H

#include "../appkit_adapter.h"

#include <QtCore/qglobal.h>

static inline qint64 hrtM6HostCall(quint64 opcode,
                                   quint64 argument1 = 0,
                                   quint64 argument2 = 0,
                                   quint64 argument3 = 0,
                                   quint64 argument4 = 0,
                                   quint64 argument5 = 0)
{
    quint64 result;
    register quint64 register10 __asm__("r10") = argument3;
    register quint64 register8 __asm__("r8") = argument4;
    register quint64 register9 __asm__("r9") = argument5;
    __asm__ volatile(
        "syscall"
        : "=a"(result), "+r"(register10),
          "+r"(register8), "+r"(register9)
        : "0"(HRT_M6_HOSTCALL_SYSCALL),
          "D"(opcode), "S"(argument1), "d"(argument2)
        : "rcx", "r11", "cc", "memory");
    return static_cast<qint64>(result);
}

#endif
