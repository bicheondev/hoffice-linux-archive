#import "appkit_adapter.h"

#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ImageIO/ImageIO.h>

#include <dispatch/dispatch.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static NSWindow *g_window;
static BOOL g_initialized;
static pthread_t g_appkit_thread;
static dispatch_source_t g_request_source;
static int g_request_pipe[2] = {-1, -1};
static int g_completion_pipe[2] = {-1, -1};
static atomic_flag g_mailbox_lock = ATOMIC_FLAG_INIT;

typedef struct {
    uint64_t opcode;
    uint64_t arguments[5];
    int64_t result;
    _Atomic unsigned int state;
} HrtM6Mailbox;

static HrtM6Mailbox g_mailbox;

static BOOL on_appkit_thread(void) {
    return g_initialized && pthread_equal(pthread_self(), g_appkit_thread) != 0;
}

static int set_close_on_exec(int fd) {
    int flags = fcntl(fd, F_GETFD);
    if (flags < 0) return -1;
    return fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
}

static int write_token(int fd) {
    static const unsigned char token = 0xa5u;
    for (;;) {
        ssize_t written = write(fd, &token, sizeof(token));
        if (written == (ssize_t)sizeof(token)) return 0;
        if (written < 0 && errno == EINTR) continue;
        return -1;
    }
}

static int read_token(int fd) {
    unsigned char token = 0u;
    for (;;) {
        ssize_t count = read(fd, &token, sizeof(token));
        if (count == (ssize_t)sizeof(token)) return 0;
        if (count < 0 && errno == EINTR) continue;
        return -1;
    }
}

static void pump_events(NSTimeInterval seconds) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([deadline timeIntervalSinceNow] > 0.0) {
        @autoreleasepool {
            NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny
                                                untilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]
                                                   inMode:NSDefaultRunLoopMode
                                                  dequeue:YES];
            if (event != nil) [NSApp sendEvent:event];
            [NSApp updateWindows];
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                     beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.005]];
        }
    }
}

static BOOL window_server_contains(CGWindowID window_id) {
    if (window_id == 0) return NO;
    CFArrayRef records = CGWindowListCopyWindowInfo(
        kCGWindowListOptionIncludingWindow, window_id);
    if (records == NULL) return NO;

    BOOL matched = NO;
    NSArray *windows = CFBridgingRelease(records);
    const pid_t process_id = getpid();
    for (NSDictionary *record in windows) {
        NSNumber *number = record[(id)kCGWindowNumber];
        NSNumber *owner = record[(id)kCGWindowOwnerPID];
        if (number.unsignedIntValue == window_id &&
            owner.intValue == process_id) {
            matched = YES;
            break;
        }
    }
    return matched;
}

static BOOL capture_window(CGWindowID window_id, const char *path) {
    if (window_id == 0 || path == NULL || path[0] == '\0') return NO;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    CGImageRef image = CGWindowListCreateImage(
        CGRectNull, kCGWindowListOptionIncludingWindow, window_id,
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageNominalResolution);
#pragma clang diagnostic pop
    if (image == NULL) return NO;

    NSString *output_path = [NSString stringWithUTF8String:path];
    if (output_path == nil) {
        CGImageRelease(image);
        return NO;
    }
    NSURL *url = [NSURL fileURLWithPath:output_path];
    CGImageDestinationRef destination = CGImageDestinationCreateWithURL(
        (__bridge CFURLRef)url, CFSTR("public.png"), 1, NULL);
    if (destination == NULL) {
        CGImageRelease(image);
        return NO;
    }
    CGImageDestinationAddImage(destination, image, NULL);
    BOOL success = CGImageDestinationFinalize(destination);
    CFRelease(destination);
    CGImageRelease(image);
    return success;
}

static int64_t create_window(const char *guest_title,
                             uint64_t requested_width,
                             uint64_t requested_height) {
    if (!on_appkit_thread()) return -1001;
    if (guest_title == NULL) return -1002;

    const size_t title_length = strnlen(guest_title, 256u);
    if (title_length == 0u || title_length == 256u) return -1003;
    NSString *title = [[NSString alloc]
        initWithBytes:guest_title
               length:title_length
             encoding:NSUTF8StringEncoding];
    if (title == nil) return -1004;

    CGFloat width = (CGFloat)requested_width;
    CGFloat height = (CGFloat)requested_height;
    if (width < 320.0) width = 320.0;
    if (width > 1600.0) width = 1600.0;
    if (height < 240.0) height = 240.0;
    if (height > 1200.0) height = 1200.0;

    if (g_window != nil) {
        [g_window orderOut:nil];
        [g_window close];
        g_window = nil;
    }

    NSWindowStyleMask style = NSWindowStyleMaskTitled |
                              NSWindowStyleMaskClosable |
                              NSWindowStyleMaskResizable |
                              NSWindowStyleMaskMiniaturizable;
    g_window = [[NSWindow alloc]
        initWithContentRect:NSMakeRect(0.0, 0.0, width, height)
                  styleMask:style
                    backing:NSBackingStoreBuffered
                      defer:NO];
    if (g_window == nil) return -1005;

    g_window.title = title;
    g_window.releasedWhenClosed = NO;
    g_window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
                                  NSWindowCollectionBehaviorFullScreenAuxiliary;
    g_window.backgroundColor = [NSColor colorWithCalibratedRed:0.10
                                                          green:0.14
                                                           blue:0.22
                                                          alpha:1.0];

    NSTextField *heading = [NSTextField labelWithString:title];
    heading.textColor = NSColor.whiteColor;
    heading.font = [NSFont systemFontOfSize:26.0 weight:NSFontWeightBold];
    heading.alignment = NSTextAlignmentCenter;
    heading.frame = NSMakeRect(24.0, height / 2.0 + 8.0,
                               width - 48.0, 44.0);
    [g_window.contentView addSubview:heading];

    NSTextField *detail = [NSTextField labelWithString:
        @"Created by a trapped Linux x86-64 guest host call"];
    detail.textColor = [NSColor colorWithWhite:0.82 alpha:1.0];
    detail.font = [NSFont systemFontOfSize:16.0 weight:NSFontWeightRegular];
    detail.alignment = NSTextAlignmentCenter;
    detail.frame = NSMakeRect(24.0, height / 2.0 - 42.0,
                              width - 48.0, 32.0);
    [g_window.contentView addSubview:detail];

    [g_window center];
    [g_window orderFrontRegardless];
    [g_window makeKeyAndOrderFront:nil];
    [g_window displayIfNeeded];
    [NSApp activateIgnoringOtherApps:YES];
    pump_events(0.25);

    NSInteger number = g_window.windowNumber;
    return number > 0 ? (int64_t)number : -1006;
}

static int64_t query_window(uint64_t expected_number) {
    if (!on_appkit_thread() || g_window == nil) return 0;
    const NSInteger number = g_window.windowNumber;
    if (expected_number != 0u &&
        expected_number != (uint64_t)number) return -1010;

    uint64_t flags = HRT_M6_WINDOW_ALLOCATED;
    if (g_window.visible) flags |= HRT_M6_WINDOW_VISIBLE;
    if (number > 0 && window_server_contains((CGWindowID)number)) {
        flags |= HRT_M6_WINDOW_SERVER_LISTED;
    }
    if (g_window.keyWindow) flags |= HRT_M6_WINDOW_KEY;
    if (g_window.mainWindow) flags |= HRT_M6_WINDOW_MAIN;
    if ([NSScreen mainScreen] != nil) flags |= HRT_M6_SCREEN_AVAILABLE;
    flags |= HRT_M6_ON_MAIN_THREAD;
    return (int64_t)flags;
}

static int64_t perform_hostcall(uint64_t opcode,
                                uint64_t argument1,
                                uint64_t argument2,
                                uint64_t argument3,
                                uint64_t argument4,
                                uint64_t argument5) {
    (void)argument4;
    (void)argument5;
    if (!on_appkit_thread()) return -1100;

    @autoreleasepool {
        switch (opcode) {
            case HRT_M6_OP_CREATE_WINDOW:
                return create_window((const char *)(uintptr_t)argument1,
                                     argument2, argument3);
            case HRT_M6_OP_PUMP_EVENTS: {
                uint64_t milliseconds = argument1;
                if (milliseconds > 5000u) milliseconds = 5000u;
                pump_events((NSTimeInterval)milliseconds / 1000.0);
                return 0;
            }
            case HRT_M6_OP_QUERY_WINDOW:
                return query_window(argument1);
            case HRT_M6_OP_CAPTURE_WINDOW: {
                if (g_window == nil) return 0;
                const char *path = getenv("HRT_M6_CAPTURE_PATH");
                return capture_window((CGWindowID)g_window.windowNumber, path)
                    ? 1 : 0;
            }
            case HRT_M6_OP_DESTROY_WINDOW:
                if (g_window != nil) {
                    [g_window orderOut:nil];
                    [g_window close];
                    g_window = nil;
                    pump_events(0.05);
                }
                return 0;
            default:
                return -1099;
        }
    }
}

static void service_mailbox(void) {
    if (read_token(g_request_pipe[0]) != 0) {
        fprintf(stderr, "hrt-m6-hostcall: request pipe read failed: %s\n",
                strerror(errno));
        fflush(stderr);
        return;
    }
    if (atomic_load_explicit(&g_mailbox.state,
                             memory_order_acquire) != 1u) {
        fprintf(stderr,
                "hrt-m6-hostcall: request arrived in invalid mailbox state\n");
        fflush(stderr);
        return;
    }

    int64_t result = perform_hostcall(
        g_mailbox.opcode,
        g_mailbox.arguments[0],
        g_mailbox.arguments[1],
        g_mailbox.arguments[2],
        g_mailbox.arguments[3],
        g_mailbox.arguments[4]);
    g_mailbox.result = result;
    atomic_store_explicit(&g_mailbox.state, 2u, memory_order_release);
    if (write_token(g_completion_pipe[1]) != 0) {
        fprintf(stderr,
                "hrt-m6-hostcall: completion pipe write failed: %s\n",
                strerror(errno));
        fflush(stderr);
    }
}

int hrt_m6_appkit_initialize(void) {
    @autoreleasepool {
        if (!pthread_main_np()) return -1;
        NSApplication *application = [NSApplication sharedApplication];
        if (application == nil) return -2;
        [application setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [application finishLaunching];

        if (pipe(g_request_pipe) != 0) return -3;
        if (pipe(g_completion_pipe) != 0) {
            int saved_errno = errno;
            (void)close(g_request_pipe[0]);
            (void)close(g_request_pipe[1]);
            g_request_pipe[0] = -1;
            g_request_pipe[1] = -1;
            errno = saved_errno;
            return -4;
        }
        for (size_t index = 0u; index < 2u; ++index) {
            if (set_close_on_exec(g_request_pipe[index]) != 0 ||
                set_close_on_exec(g_completion_pipe[index]) != 0) {
                return -5;
            }
        }

        g_appkit_thread = pthread_self();
        atomic_init(&g_mailbox.state, 0u);
        g_request_source = dispatch_source_create(
            DISPATCH_SOURCE_TYPE_READ,
            (uintptr_t)g_request_pipe[0], 0u,
            dispatch_get_main_queue());
        if (g_request_source == nil) return -6;
        dispatch_source_set_event_handler(g_request_source, ^{
            service_mailbox();
        });
        dispatch_activate(g_request_source);

        g_initialized = YES;
        fprintf(stderr,
                "hrt-m6-hostcall: AppKit initialized on pid=%d main-thread=1 "
                "request-fd=%d completion-fd=%d\n",
                (int)getpid(), g_request_pipe[1], g_completion_pipe[0]);
        fflush(stderr);
        return 0;
    }
}

void hrt_m6_appkit_run(void) {
    @autoreleasepool {
        if (!on_appkit_thread()) {
            fprintf(stderr,
                    "hrt-m6-hostcall: AppKit run loop requested off thread\n");
            fflush(stderr);
            return;
        }
        [NSApp run];
        fprintf(stderr, "hrt-m6-hostcall: AppKit run loop returned\n");
        fflush(stderr);
    }
}

int64_t hrt_m6_appkit_hostcall(uint64_t opcode,
                               uint64_t argument1,
                               uint64_t argument2,
                               uint64_t argument3,
                               uint64_t argument4,
                               uint64_t argument5) {
    if (!g_initialized) return -1110;
    if (on_appkit_thread()) {
        return perform_hostcall(opcode, argument1, argument2, argument3,
                                argument4, argument5);
    }

    while (atomic_flag_test_and_set_explicit(
               &g_mailbox_lock, memory_order_acquire)) {
        __asm__ volatile("pause");
    }

    g_mailbox.opcode = opcode;
    g_mailbox.arguments[0] = argument1;
    g_mailbox.arguments[1] = argument2;
    g_mailbox.arguments[2] = argument3;
    g_mailbox.arguments[3] = argument4;
    g_mailbox.arguments[4] = argument5;
    g_mailbox.result = -1111;
    atomic_store_explicit(&g_mailbox.state, 1u, memory_order_release);

    if (write_token(g_request_pipe[1]) != 0) {
        atomic_store_explicit(&g_mailbox.state, 0u, memory_order_release);
        atomic_flag_clear_explicit(&g_mailbox_lock, memory_order_release);
        return -1112;
    }
    if (read_token(g_completion_pipe[0]) != 0) {
        atomic_store_explicit(&g_mailbox.state, 0u, memory_order_release);
        atomic_flag_clear_explicit(&g_mailbox_lock, memory_order_release);
        return -1113;
    }
    if (atomic_load_explicit(&g_mailbox.state,
                             memory_order_acquire) != 2u) {
        atomic_store_explicit(&g_mailbox.state, 0u, memory_order_release);
        atomic_flag_clear_explicit(&g_mailbox_lock, memory_order_release);
        return -1114;
    }

    int64_t result = g_mailbox.result;
    atomic_store_explicit(&g_mailbox.state, 0u, memory_order_release);
    atomic_flag_clear_explicit(&g_mailbox_lock, memory_order_release);
    return result;
}
