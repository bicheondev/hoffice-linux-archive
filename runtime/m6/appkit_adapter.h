#ifndef HRT_M6_APPKIT_ADAPTER_H
#define HRT_M6_APPKIT_ADAPTER_H

#include <stdint.h>

#define HRT_M6_HOSTCALL_SYSCALL UINT64_C(0x3fff0000)

#define HRT_M6_OP_CREATE_WINDOW UINT64_C(0x100)
#define HRT_M6_OP_PUMP_EVENTS   UINT64_C(0x101)
#define HRT_M6_OP_QUERY_WINDOW  UINT64_C(0x102)
#define HRT_M6_OP_CAPTURE_WINDOW UINT64_C(0x103)
#define HRT_M6_OP_DESTROY_WINDOW UINT64_C(0x104)

#define HRT_M6_WINDOW_ALLOCATED UINT64_C(0x01)
#define HRT_M6_WINDOW_VISIBLE UINT64_C(0x02)
#define HRT_M6_WINDOW_SERVER_LISTED UINT64_C(0x04)
#define HRT_M6_WINDOW_KEY UINT64_C(0x08)
#define HRT_M6_WINDOW_MAIN UINT64_C(0x10)
#define HRT_M6_SCREEN_AVAILABLE UINT64_C(0x20)
#define HRT_M6_ON_MAIN_THREAD UINT64_C(0x40)

#ifdef __cplusplus
extern "C" {
#endif

int hrt_m6_appkit_initialize(void);

int64_t hrt_m6_appkit_hostcall(uint64_t opcode,
                               uint64_t argument1,
                               uint64_t argument2,
                               uint64_t argument3,
                               uint64_t argument4,
                               uint64_t argument5);

#ifdef __cplusplus
}
#endif

#endif
