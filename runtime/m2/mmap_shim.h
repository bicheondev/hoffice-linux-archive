#ifndef HRT_M2_MMAP_SHIM_H
#define HRT_M2_MMAP_SHIM_H

#include <stddef.h>
#include <sys/mman.h>
#include <sys/types.h>

void *hrt_host_mmap(void *address, size_t length, int protection,
                    int flags, int descriptor, off_t offset);

#define mmap hrt_host_mmap

#endif
