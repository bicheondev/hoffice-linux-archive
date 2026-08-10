#ifndef HRT_M8_INPUT_PROTOCOL_H
#define HRT_M8_INPUT_PROTOCOL_H

#include <stdint.h>

#define HRT_M8_INPUT_ABI_VERSION UINT32_C(1)
#define HRT_M8_INPUT_TEXT_BYTES 24u

#define HRT_M8_OP_POLL_INPUT UINT64_C(0x106)

#define HRT_M8_EVENT_KEY UINT32_C(1)
#define HRT_M8_EVENT_MOUSE UINT32_C(2)

/* Key-event actions are distinct from the Qt logical-key namespace below. */
#define HRT_M8_KEY_ACTION_DOWN UINT32_C(1)
#define HRT_M8_KEY_ACTION_UP UINT32_C(2)

#define HRT_M8_MOUSE_MOVE UINT32_C(1)
#define HRT_M8_MOUSE_DOWN UINT32_C(2)
#define HRT_M8_MOUSE_UP UINT32_C(3)
#define HRT_M8_MOUSE_DRAG UINT32_C(4)

#define HRT_M8_MOD_SHIFT UINT32_C(0x01)
#define HRT_M8_MOD_CONTROL UINT32_C(0x02)
#define HRT_M8_MOD_ALT UINT32_C(0x04)
#define HRT_M8_MOD_META UINT32_C(0x08)
#define HRT_M8_MOD_CAPS_LOCK UINT32_C(0x10)

#define HRT_M8_BUTTON_NONE UINT32_C(0)
#define HRT_M8_BUTTON_LEFT UINT32_C(0x01)
#define HRT_M8_BUTTON_RIGHT UINT32_C(0x02)
#define HRT_M8_BUTTON_MIDDLE UINT32_C(0x04)
#define HRT_M8_BUTTON_X1 UINT32_C(0x08)
#define HRT_M8_BUTTON_X2 UINT32_C(0x10)

/* Qt 5 keyboard values used by the host-side macOS key mapper. */
#define HRT_M8_KEY_ESCAPE UINT32_C(0x01000000)
#define HRT_M8_KEY_TAB UINT32_C(0x01000001)
#define HRT_M8_KEY_BACKTAB UINT32_C(0x01000002)
#define HRT_M8_KEY_BACKSPACE UINT32_C(0x01000003)
#define HRT_M8_KEY_RETURN UINT32_C(0x01000004)
#define HRT_M8_KEY_ENTER UINT32_C(0x01000005)
#define HRT_M8_KEY_INSERT UINT32_C(0x01000006)
#define HRT_M8_KEY_DELETE UINT32_C(0x01000007)
#define HRT_M8_KEY_HOME UINT32_C(0x01000010)
#define HRT_M8_KEY_END UINT32_C(0x01000011)
#define HRT_M8_KEY_LEFT UINT32_C(0x01000012)
#define HRT_M8_KEY_UP UINT32_C(0x01000013)
#define HRT_M8_KEY_RIGHT UINT32_C(0x01000014)
#define HRT_M8_KEY_DOWN_ARROW UINT32_C(0x01000015)
#define HRT_M8_KEY_PAGE_UP UINT32_C(0x01000016)
#define HRT_M8_KEY_PAGE_DOWN UINT32_C(0x01000017)

/*
 * Stable same-process ABI copied by HRT_M8_OP_POLL_INPUT.  The structure is
 * deliberately pointer-free so the Linux x86-64 guest and macOS host agree on
 * every byte without sharing Objective-C or Qt types.
 */
typedef struct {
    uint32_t size;
    uint32_t type;
    uint64_t sequence;
    uint32_t action;
    uint32_t modifiers;
    uint32_t logical_key;
    uint32_t native_key;
    uint32_t button;
    uint32_t buttons;
    int32_t x;
    int32_t y;
    int32_t global_x;
    int32_t global_y;
    uint32_t utf8_length;
    uint32_t reserved;
    char utf8[HRT_M8_INPUT_TEXT_BYTES];
} HrtM8InputEvent;

#if defined(__cplusplus)
static_assert(sizeof(HrtM8InputEvent) == 88u,
              "M8 input event ABI size");
#else
_Static_assert(sizeof(HrtM8InputEvent) == 88u,
               "M8 input event ABI size");
#endif

#endif
