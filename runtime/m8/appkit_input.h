#ifndef HRT_M8_APPKIT_INPUT_H
#define HRT_M8_APPKIT_INPUT_H

#include "input_protocol.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

int hrt_m8_input_attach(void *window_pointer);
void hrt_m8_input_reset(void);
int64_t hrt_m8_input_poll(HrtM8InputEvent *output, uint64_t output_size);
void hrt_m8_input_inject_if_requested(void *window_pointer);

#ifdef __cplusplus
}
#endif

#endif
