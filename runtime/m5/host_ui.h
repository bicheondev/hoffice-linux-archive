#ifndef HRT_M5_HOST_UI_H
#define HRT_M5_HOST_UI_H

#include <stddef.h>
#include <stdint.h>

#define HRT_HOST_CREATE_WINDOW UINT64_C(0x7ff00001)
#define HRT_HOST_VISIBLE_WINDOWS UINT64_C(0x7ff00002)
#define HRT_HOST_WINDOW_TITLE_MAX 192u

#ifdef __cplusplus
extern "C" {
#endif

int64_t hrt_host_ui_submit_window(const char *title,
                                  size_t title_length,
                                  uint32_t width,
                                  uint32_t height);
int64_t hrt_host_ui_visible_windows(void);
void hrt_host_ui_run(void *stack_pointer, void *entry_point)
    __attribute__((noreturn));

#ifdef __cplusplus
}
#endif

#endif
