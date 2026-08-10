#import "appkit_input.h"

#import <AppKit/AppKit.h>

#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HRT_M8_QUEUE_CAPACITY 128u

static HrtM8InputEvent g_events[HRT_M8_QUEUE_CAPACITY];
static size_t g_head;
static size_t g_count;
static uint64_t g_sequence;
static uint32_t g_mouse_buttons;
static id g_event_monitor;
static __weak NSWindow *g_input_window;
static BOOL g_synthetic_input_injected;

static int32_t clamp_coordinate(CGFloat value) {
    if (value > (CGFloat)INT32_MAX) return INT32_MAX;
    if (value < (CGFloat)INT32_MIN) return INT32_MIN;
    return (int32_t)value;
}

static uint32_t translate_modifiers(NSEventModifierFlags flags) {
    uint32_t result = 0u;
    if ((flags & NSEventModifierFlagShift) != 0u)
        result |= HRT_M8_MOD_SHIFT;
    if ((flags & NSEventModifierFlagControl) != 0u)
        result |= HRT_M8_MOD_CONTROL;
    if ((flags & NSEventModifierFlagOption) != 0u)
        result |= HRT_M8_MOD_ALT;
    if ((flags & NSEventModifierFlagCommand) != 0u)
        result |= HRT_M8_MOD_META;
    if ((flags & NSEventModifierFlagCapsLock) != 0u)
        result |= HRT_M8_MOD_CAPS_LOCK;
    return result;
}

static uint32_t translate_button(NSInteger number) {
    switch (number) {
        case 0: return HRT_M8_BUTTON_LEFT;
        case 1: return HRT_M8_BUTTON_RIGHT;
        case 2: return HRT_M8_BUTTON_MIDDLE;
        case 3: return HRT_M8_BUTTON_X1;
        case 4: return HRT_M8_BUTTON_X2;
        default: return HRT_M8_BUTTON_NONE;
    }
}

static uint32_t translate_key(NSEvent *event) {
    switch (event.keyCode) {
        case 36: return HRT_M8_KEY_RETURN;
        case 48: return HRT_M8_KEY_TAB;
        case 51: return HRT_M8_KEY_BACKSPACE;
        case 53: return HRT_M8_KEY_ESCAPE;
        case 115: return HRT_M8_KEY_HOME;
        case 116: return HRT_M8_KEY_PAGE_UP;
        case 117: return HRT_M8_KEY_DELETE;
        case 119: return HRT_M8_KEY_END;
        case 121: return HRT_M8_KEY_PAGE_DOWN;
        case 123: return HRT_M8_KEY_LEFT;
        case 124: return HRT_M8_KEY_RIGHT;
        case 125: return HRT_M8_KEY_DOWN_ARROW;
        case 126: return HRT_M8_KEY_UP;
        default: break;
    }

    NSString *characters = event.charactersIgnoringModifiers;
    if (characters.length == 0u) return 0u;
    unichar value = [characters characterAtIndex:0u];
    if (value >= (unichar)'a' && value <= (unichar)'z')
        value = (unichar)(value - (unichar)'a' + (unichar)'A');
    return (uint32_t)value;
}

static void copy_text(HrtM8InputEvent *event, NSString *text) {
    if (text == nil || text.length == 0u) return;
    NSData *encoded = [text dataUsingEncoding:NSUTF8StringEncoding];
    if (encoded == nil || encoded.length == 0u) return;
    NSUInteger length = encoded.length;
    if (length > HRT_M8_INPUT_TEXT_BYTES)
        length = HRT_M8_INPUT_TEXT_BYTES;
    memcpy(event->utf8, encoded.bytes, length);
    event->utf8_length = (uint32_t)length;
}

static void global_coordinates_for_event(NSEvent *event, NSWindow *window,
                                         int32_t *x, int32_t *y) {
    NSPoint point = [NSEvent mouseLocation];
    if (event != nil && window != nil &&
        event.windowNumber == window.windowNumber) {
        /*
         * Synthetic events do not move the physical cursor, so
         * +mouseLocation remains at the runner's idle cursor position.  Qt
         * receives both local and global coordinates and can reject a click
         * whose pair is inconsistent.  Derive the screen point from the
         * event's window-local coordinate whenever possible.
         */
        point = [window convertPointToScreen:event.locationInWindow];
    }

    NSScreen *selected = nil;
    for (NSScreen *screen in NSScreen.screens) {
        if (NSPointInRect(point, screen.frame)) {
            selected = screen;
            break;
        }
    }
    if (selected == nil && window != nil)
        selected = window.screen;
    if (selected == nil)
        selected = NSScreen.mainScreen;
    *x = clamp_coordinate(point.x);
    *y = selected != nil
        ? clamp_coordinate(NSMaxY(selected.frame) - point.y)
        : clamp_coordinate(point.y);
}

static void enqueue_event(const HrtM8InputEvent *event) {
    if (g_count == HRT_M8_QUEUE_CAPACITY) {
        g_head = (g_head + 1u) % HRT_M8_QUEUE_CAPACITY;
        --g_count;
        fputs("HRT M8 APPKIT: input queue overflow dropped oldest event\n",
              stderr);
    }
    const size_t index = (g_head + g_count) % HRT_M8_QUEUE_CAPACITY;
    g_events[index] = *event;
    ++g_count;

    if (event->type == HRT_M8_EVENT_KEY) {
        fprintf(stderr,
                "HRT M8 APPKIT: queued key sequence=%llu action=%u key=0x%x native=%u text-bytes=%u\n",
                (unsigned long long)event->sequence, event->action,
                event->logical_key, event->native_key, event->utf8_length);
    } else {
        fprintf(stderr,
                "HRT M8 APPKIT: queued mouse sequence=%llu action=%u button=0x%x buttons=0x%x local=%d,%d global=%d,%d\n",
                (unsigned long long)event->sequence, event->action,
                event->button, event->buttons, event->x, event->y,
                event->global_x, event->global_y);
    }
    fflush(stderr);
}

static void capture_key_event(NSEvent *event, uint32_t action) {
    HrtM8InputEvent output;
    memset(&output, 0, sizeof(output));
    output.size = (uint32_t)sizeof(output);
    output.type = HRT_M8_EVENT_KEY;
    output.sequence = ++g_sequence;
    output.action = action;
    output.modifiers = translate_modifiers(event.modifierFlags);
    output.logical_key = translate_key(event);
    output.native_key = event.keyCode;
    copy_text(&output, event.characters);
    enqueue_event(&output);
}

static void capture_mouse_event(NSEvent *event, uint32_t action) {
    HrtM8InputEvent output;
    memset(&output, 0, sizeof(output));
    output.size = (uint32_t)sizeof(output);
    output.type = HRT_M8_EVENT_MOUSE;
    output.sequence = ++g_sequence;
    output.action = action;
    output.modifiers = translate_modifiers(event.modifierFlags);
    output.button = translate_button(event.buttonNumber);

    if (action == HRT_M8_MOUSE_DOWN)
        g_mouse_buttons |= output.button;
    else if (action == HRT_M8_MOUSE_UP)
        g_mouse_buttons &= ~output.button;
    output.buttons = g_mouse_buttons;

    NSWindow *window = g_input_window;
    NSPoint local = event.locationInWindow;
    if (window.contentView != nil)
        local = [window.contentView convertPoint:local fromView:nil];
    output.x = clamp_coordinate(local.x);
    output.y = clamp_coordinate(local.y);
    global_coordinates_for_event(
        event, window, &output.global_x, &output.global_y);
    enqueue_event(&output);
}

static NSEvent *monitor_event(NSEvent *event) {
    NSWindow *window = g_input_window;
    if (window == nil) return event;
    if (event.windowNumber != 0 && event.windowNumber != window.windowNumber)
        return event;

    switch (event.type) {
        case NSEventTypeKeyDown:
            capture_key_event(event, HRT_M8_KEY_ACTION_DOWN);
            break;
        case NSEventTypeKeyUp:
            capture_key_event(event, HRT_M8_KEY_ACTION_UP);
            break;
        case NSEventTypeMouseMoved:
            capture_mouse_event(event, HRT_M8_MOUSE_MOVE);
            break;
        case NSEventTypeLeftMouseDown:
        case NSEventTypeRightMouseDown:
        case NSEventTypeOtherMouseDown:
            capture_mouse_event(event, HRT_M8_MOUSE_DOWN);
            break;
        case NSEventTypeLeftMouseUp:
        case NSEventTypeRightMouseUp:
        case NSEventTypeOtherMouseUp:
            capture_mouse_event(event, HRT_M8_MOUSE_UP);
            break;
        case NSEventTypeLeftMouseDragged:
        case NSEventTypeRightMouseDragged:
        case NSEventTypeOtherMouseDragged:
            capture_mouse_event(event, HRT_M8_MOUSE_DRAG);
            break;
        default:
            break;
    }
    return event;
}

void hrt_m8_input_reset(void) {
    if (g_event_monitor != nil) {
        [NSEvent removeMonitor:g_event_monitor];
        g_event_monitor = nil;
    }
    g_input_window = nil;
    g_head = 0u;
    g_count = 0u;
    g_sequence = 0u;
    g_mouse_buttons = 0u;
    g_synthetic_input_injected = NO;
    memset(g_events, 0, sizeof(g_events));
}

int hrt_m8_input_attach(void *window_pointer) {
    if (![NSThread isMainThread]) return -1;
    NSWindow *window = (__bridge NSWindow *)window_pointer;
    if (window == nil) return -2;

    hrt_m8_input_reset();
    g_input_window = window;
    window.acceptsMouseMovedEvents = YES;
    if (window.contentView != nil)
        [window makeFirstResponder:window.contentView];

    NSEventMask mask = NSEventMaskKeyDown | NSEventMaskKeyUp |
        NSEventMaskMouseMoved | NSEventMaskLeftMouseDown |
        NSEventMaskLeftMouseUp | NSEventMaskRightMouseDown |
        NSEventMaskRightMouseUp | NSEventMaskOtherMouseDown |
        NSEventMaskOtherMouseUp | NSEventMaskLeftMouseDragged |
        NSEventMaskRightMouseDragged | NSEventMaskOtherMouseDragged;
    g_event_monitor = [NSEvent addLocalMonitorForEventsMatchingMask:mask
        handler:^NSEvent *(NSEvent *event) {
            return monitor_event(event);
        }];
    if (g_event_monitor == nil) return -3;
    fprintf(stderr, "HRT M8 APPKIT: input monitor attached window=%ld\n",
            (long)window.windowNumber);
    fflush(stderr);
    return 0;
}

int64_t hrt_m8_input_poll(HrtM8InputEvent *output, uint64_t output_size) {
    if (![NSThread isMainThread]) return -1;
    if (output == NULL) return -2;
    if (output_size < sizeof(HrtM8InputEvent)) return -3;
    if (g_count == 0u) return 0;

    *output = g_events[g_head];
    memset(&g_events[g_head], 0, sizeof(g_events[g_head]));
    g_head = (g_head + 1u) % HRT_M8_QUEUE_CAPACITY;
    --g_count;
    fprintf(stderr,
            "HRT M8 APPKIT: delivered event sequence=%llu type=%u action=%u remaining=%zu\n",
            (unsigned long long)output->sequence, output->type,
            output->action, g_count);
    fflush(stderr);
    return 1;
}

static NSEvent *synthetic_key(NSEventType type, NSWindow *window) {
    return [NSEvent keyEventWithType:type
                           location:NSZeroPoint
                      modifierFlags:0
                          timestamp:NSProcessInfo.processInfo.systemUptime
                       windowNumber:window.windowNumber
                            context:nil
                         characters:@"a"
        charactersIgnoringModifiers:@"a"
                           isARepeat:NO
                             keyCode:0];
}

static NSEvent *synthetic_mouse(NSEventType type, NSWindow *window,
                                NSPoint location, NSInteger event_number) {
    return [NSEvent mouseEventWithType:type
                             location:location
                        modifierFlags:0
                            timestamp:NSProcessInfo.processInfo.systemUptime
                         windowNumber:window.windowNumber
                              context:nil
                          eventNumber:event_number
                           clickCount:(type == NSEventTypeLeftMouseDown ||
                                       type == NSEventTypeLeftMouseUp) ? 1 : 0
                             pressure:(type == NSEventTypeLeftMouseDown) ? 1.0 : 0.0];
}

void hrt_m8_input_inject_if_requested(void *window_pointer) {
    if (g_synthetic_input_injected) return;
    const char *requested = getenv("HRT_M8_SYNTHETIC_INPUT");
    if (requested == NULL || strcmp(requested, "1") != 0) return;
    if (![NSThread isMainThread]) return;

    NSWindow *window = (__bridge NSWindow *)window_pointer;
    if (window == nil || window != g_input_window) return;
    g_synthetic_input_injected = YES;

    const NSRect bounds = window.contentView != nil
        ? window.contentView.bounds : NSMakeRect(0.0, 0.0, 640.0, 480.0);
    NSPoint point = NSMakePoint(NSMidX(bounds), NSMidY(bounds));
    NSArray<NSEvent *> *events = @[
        synthetic_mouse(NSEventTypeMouseMoved, window, point, 8001),
        synthetic_mouse(NSEventTypeLeftMouseDown, window, point, 8002),
        synthetic_mouse(NSEventTypeLeftMouseUp, window, point, 8003),
        synthetic_key(NSEventTypeKeyDown, window),
        synthetic_key(NSEventTypeKeyUp, window),
    ];
    for (NSEvent *event in events)
        [NSApp postEvent:event atStart:NO];
    fprintf(stderr,
            "HRT M8 APPKIT: posted deterministic focus click, key and mouse events window=%ld\n",
            (long)window.windowNumber);
    fflush(stderr);
}
