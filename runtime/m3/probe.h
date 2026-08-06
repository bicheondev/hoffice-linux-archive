#ifndef HRT_M3_PROBE_H
#define HRT_M3_PROBE_H

#include <stdint.h>

extern uintptr_t g_m3_entry_probe;
void install_main_entry_probe(uintptr_t entry_address);

#endif
