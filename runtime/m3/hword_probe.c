#define _DARWIN_C_SOURCE 1
#include "hrt_m3.h"
#include "probe.h"

#include <errno.h>
#include <stdint.h>
#include <sys/mman.h>

uintptr_t g_m3_entry_probe;

void install_main_entry_probe(uintptr_t entry_address) {
    if (entry_address == 0u) {
        errno = EINVAL;
        fatal("invalid HWord entry probe address");
    }

    uintptr_t page = align_down(entry_address, g_page_size);
    if (mprotect((void *)page, g_page_size,
                 PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
        fatal("mprotect HWord entry probe page writable");
    }

    unsigned char *instruction = (unsigned char *)entry_address;
    instruction[0] = 0x0fu;
    instruction[1] = 0x0bu;
    __builtin___clear_cache((char *)instruction, (char *)instruction + 2);

    if (mprotect((void *)page, g_page_size,
                 PROT_READ | PROT_EXEC) != 0) {
        fatal("mprotect HWord entry probe page executable");
    }
    g_m3_entry_probe = entry_address;
}
