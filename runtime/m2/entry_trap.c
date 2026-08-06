#include "hrt_m2.h"

#include <errno.h>

void arm_entry_trap(uintptr_t address) {
    if (address == 0u || g_runtime.entry_trap_armed) {
        errno = 0;
        fatal("invalid M3 entry-trap request");
    }
    unsigned char *instruction = (unsigned char *)address;
    g_runtime.entry_trap_original[0] = instruction[0];
    g_runtime.entry_trap_original[1] = instruction[1];
    g_runtime.entry_trap_address = address;
    g_runtime.entry_trap_armed = 1;
    instruction[0] = 0x0f;
    instruction[1] = 0x0b;
#if defined(__clang__) || defined(__GNUC__)
    __builtin___clear_cache((char *)instruction, (char *)instruction + 2);
#endif
}
