#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>

#include "host_ui.h"
#include "../m2/hrt_m2.h"

#include <dispatch/dispatch.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

typedef struct {
    uint64_t request_id;
    uint32_t width;
    uint32_t height;
    uint32_t title_length;
    uint32_t reserved;
    char title[HRT_HOST_WINDOW_TITLE_MAX];
} HrtHostWindowRequest;

typedef struct {
    void *stack_pointer;
    void *entry_point;
} HrtGuestLaunch;

static int g_request_socket[2] = {-1, -1};
static volatile sig_atomic_t g_visible_window_count;
static volatile sig_atomic_t g_next_request_id = 1;
static dispatch_source_t g_request_source;
static NSMutableArray<NSWindow *> *g_windows;

static void write_all_stderr(const char *text) {
    size_t length = strlen(text);
    while (length != 0u) {
        ssize_t count = write(STDERR_FILENO, text, length);
        if (count < 0) {
            if (errno == EINTR) continue;
            return;
        }
        text += count;
        length -= (size_t)count;
    }
}

int64_t hrt_host_ui_submit_window(const char *title,
                                  size_t title_length,
                                  uint32_t width,
                                  uint32_t height) {
    if (g_request_socket[0] < 0) return -19;
    if (title == NULL && title_length != 0u) return -14;

    HrtHostWindowRequest request;
    memset(&request, 0, sizeof(request));
    sig_atomic_t identifier = g_next_request_id++;
    if (identifier <= 0) {
        identifier = 1;
        g_next_request_id = 2;
    }
    request.request_id = (uint64_t)identifier;
    request.width = width;
    request.height = height;
    if (title_length >= sizeof(request.title)) {
        title_length = sizeof(request.title) - 1u;
    }
    request.title_length = (uint32_t)title_length;
    for (size_t index = 0; index < title_length; ++index) {
        request.title[index] = title[index];
    }
    request.title[title_length] = '\0';

    ssize_t written;
    do {
        written = write(g_request_socket[0], &request, sizeof(request));
    } while (written < 0 && errno == EINTR);
    if (written != (ssize_t)sizeof(request)) return -5;
    return (int64_t)request.request_id;
}

int64_t hrt_host_ui_visible_windows(void) {
    return (int64_t)g_visible_window_count;
}

static NSString *request_title(const HrtHostWindowRequest *request) {
    NSUInteger length = request->title_length;
    if (length >= sizeof(request->title)) {
        length = sizeof(request->title) - 1u;
    }
    NSString *title = [[NSString alloc]
        initWithBytes:request->title
               length:length
             encoding:NSUTF8StringEncoding];
    return title ?: @"한컴오피스 2022 Beta";
}

static void write_marker(NSWindow *window,
                         const HrtHostWindowRequest *request,
                         NSString *title) {
    NSString *markerPath = NSProcessInfo.processInfo.environment[
        @"HRT_HOST_WINDOW_MARKER_PATH"];
    if (markerPath.length != 0u) {
        NSDictionary *marker = @{
            @"schemaVersion": @1,
            @"requestID": @(request->request_id),
            @"windowNumber": @(window.windowNumber),
            @"visible": @(window.visible),
            @"title": title,
            @"width": @(request->width),
            @"height": @(request->height),
        };
        NSError *error = nil;
        NSData *json = [NSJSONSerialization
            dataWithJSONObject:marker
                       options:NSJSONWritingPrettyPrinted
                         error:&error];
        if (json != nil) {
            [json writeToFile:markerPath
                      options:NSDataWritingAtomic
                        error:&error];
        }
        if (error != nil) {
            fprintf(stderr, "hrt-m5: marker write failed: %s\n",
                    error.localizedDescription.UTF8String);
        }
    }

    NSString *imagePath = NSProcessInfo.processInfo.environment[
        @"HRT_HOST_SCREENSHOT_PATH"];
    NSView *contentView = window.contentView;
    if (imagePath.length != 0u && contentView != nil) {
        [contentView layoutSubtreeIfNeeded];
        [window displayIfNeeded];
        NSBitmapImageRep *bitmap = [contentView
            bitmapImageRepForCachingDisplayInRect:contentView.bounds];
        if (bitmap != nil) {
            [contentView cacheDisplayInRect:contentView.bounds
                         toBitmapImageRep:bitmap];
            NSData *png = [bitmap
                representationUsingType:NSBitmapImageFileTypePNG
                              properties:@{}];
            if (png != nil) {
                [png writeToFile:imagePath atomically:YES];
            }
        }
    }
}

static void create_window(const HrtHostWindowRequest *request) {
    CGFloat width = request->width >= 320u ? request->width : 920u;
    CGFloat height = request->height >= 240u ? request->height : 640u;
    NSString *title = request_title(request);
    NSRect frame = NSMakeRect(0.0, 0.0, width, height);
    NSWindowStyleMask style = NSWindowStyleMaskTitled |
        NSWindowStyleMaskClosable |
        NSWindowStyleMaskMiniaturizable |
        NSWindowStyleMaskResizable;
    NSWindow *window = [[NSWindow alloc]
        initWithContentRect:frame
                  styleMask:style
                    backing:NSBackingStoreBuffered
                      defer:NO];
    window.releasedWhenClosed = NO;
    window.title = title;
    window.backgroundColor = NSColor.windowBackgroundColor;
    window.minSize = NSMakeSize(480.0, 320.0);

    NSView *content = [[NSView alloc] initWithFrame:frame];
    NSTextField *headline = [NSTextField
        labelWithString:@"한컴오피스 2022 Beta"];
    headline.alignment = NSTextAlignmentCenter;
    headline.font = [NSFont systemFontOfSize:25.0
                                      weight:NSFontWeightSemibold];
    headline.frame = NSMakeRect(40.0, height / 2.0 + 8.0,
                                width - 80.0, 42.0);
    headline.autoresizingMask = NSViewWidthSizable |
                                NSViewMinYMargin |
                                NSViewMaxYMargin;
    [content addSubview:headline];

    NSTextField *detail = [NSTextField
        labelWithString:@"Linux guest → macOS AppKit host-call bridge"];
    detail.alignment = NSTextAlignmentCenter;
    detail.textColor = NSColor.secondaryLabelColor;
    detail.font = [NSFont systemFontOfSize:14.0];
    detail.frame = NSMakeRect(40.0, height / 2.0 - 34.0,
                              width - 80.0, 28.0);
    detail.autoresizingMask = NSViewWidthSizable |
                              NSViewMinYMargin |
                              NSViewMaxYMargin;
    [content addSubview:detail];
    window.contentView = content;

    [g_windows addObject:window];
    [window center];
    [window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    [window displayIfNeeded];

    write_marker(window, request, title);
    fprintf(stderr,
            "hrt-m5: AppKit window visible request=%llu number=%ld "
            "title=%s size=%ux%u\n",
            (unsigned long long)request->request_id,
            (long)window.windowNumber,
            title.UTF8String,
            request->width,
            request->height);
    fflush(stderr);
    ++g_visible_window_count;
}

static void drain_window_requests(void) {
    for (;;) {
        HrtHostWindowRequest request;
        ssize_t count = recv(g_request_socket[1], &request,
                             sizeof(request), MSG_DONTWAIT);
        if (count < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) return;
            write_all_stderr("hrt-m5: host request socket failed\n");
            return;
        }
        if (count == 0) return;
        if (count != (ssize_t)sizeof(request)) {
            write_all_stderr("hrt-m5: malformed host window request\n");
            continue;
        }
        @autoreleasepool {
            create_window(&request);
        }
    }
}

static void *guest_thread_main(void *opaque) {
    HrtGuestLaunch launch = *(HrtGuestLaunch *)opaque;
    free(opaque);
    enter_guest(launch.stack_pointer, launch.entry_point);
}

void hrt_host_ui_run(void *stack_pointer, void *entry_point) {
    @autoreleasepool {
        if (socketpair(AF_UNIX, SOCK_DGRAM, 0, g_request_socket) != 0) {
            fatal("socketpair for AppKit host bridge");
        }
        int yes = 1;
        (void)setsockopt(g_request_socket[0], SOL_SOCKET, SO_NOSIGPIPE,
                         &yes, sizeof(yes));
        (void)setsockopt(g_request_socket[1], SOL_SOCKET, SO_NOSIGPIPE,
                         &yes, sizeof(yes));
        int flags = fcntl(g_request_socket[1], F_GETFL);
        if (flags >= 0) {
            (void)fcntl(g_request_socket[1], F_SETFL,
                        flags | O_NONBLOCK);
        }

        NSApplication *application = NSApplication.sharedApplication;
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        g_windows = [[NSMutableArray alloc] init];

        g_request_source = dispatch_source_create(
            DISPATCH_SOURCE_TYPE_READ,
            (uintptr_t)g_request_socket[1],
            0,
            dispatch_get_main_queue());
        dispatch_source_set_event_handler(g_request_source, ^{
            drain_window_requests();
        });
        dispatch_resume(g_request_source);
        [application finishLaunching];

        HrtGuestLaunch *launch = malloc(sizeof(*launch));
        if (launch == NULL) fatal("allocate guest launch context");
        launch->stack_pointer = stack_pointer;
        launch->entry_point = entry_point;
        pthread_t guest_thread;
        int result = pthread_create(&guest_thread, NULL,
                                    guest_thread_main, launch);
        if (result != 0) {
            free(launch);
            errno = result;
            fatal("create Linux guest thread");
        }
        (void)pthread_detach(guest_thread);

        write_all_stderr("hrt-m5: AppKit host run loop started\n");
        [application run];
    }
    _exit(70);
}
