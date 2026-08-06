#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ImageIO/ImageIO.h>

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void pump_main_run_loop(NSTimeInterval seconds) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([deadline timeIntervalSinceNow] > 0.0) {
        @autoreleasepool {
            NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny
                                                untilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]
                                                   inMode:NSDefaultRunLoopMode
                                                  dequeue:YES];
            if (event != nil) [NSApp sendEvent:event];
            [NSApp updateWindows];
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                     beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
        }
    }
}

static BOOL window_server_contains(CGWindowID window_id, pid_t owner_pid,
                                   NSString *expected_title) {
    CFArrayRef records = CGWindowListCopyWindowInfo(
        kCGWindowListOptionIncludingWindow, window_id);
    if (records == NULL) return NO;

    BOOL matched = NO;
    NSArray *windows = CFBridgingRelease(records);
    for (NSDictionary *record in windows) {
        NSNumber *number = record[(id)kCGWindowNumber];
        NSNumber *pid = record[(id)kCGWindowOwnerPID];
        NSString *title = record[(id)kCGWindowName];
        if (number.unsignedIntValue == window_id &&
            pid.intValue == owner_pid &&
            (title == nil || [title isEqualToString:expected_title])) {
            matched = YES;
            break;
        }
    }
    return matched;
}

static BOOL capture_window(CGWindowID window_id, const char *output_path) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    CGImageRef image = CGWindowListCreateImage(
        CGRectNull, kCGWindowListOptionIncludingWindow, window_id,
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageNominalResolution);
#pragma clang diagnostic pop
    if (image == NULL) return NO;

    NSString *path = [NSString stringWithUTF8String:output_path];
    NSURL *url = [NSURL fileURLWithPath:path];
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

int main(int argc, const char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s OUTPUT.png\n", argv[0]);
        return 64;
    }

    @autoreleasepool {
        const pid_t pid = getpid();
        const NSString *title = @"HRT M6 AppKit Host Probe";

        NSApplication *application = [NSApplication sharedApplication];
        if (application == nil) {
            fputs("hrt-m6-host: NSApplication initialization failed\n", stderr);
            return 1;
        }
        [application setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [application finishLaunching];

        NSScreen *screen = [NSScreen mainScreen];
        NSRect frame = NSMakeRect(120.0, 120.0, 640.0, 420.0);
        if (screen != nil) {
            NSRect visible = screen.visibleFrame;
            frame.origin.x = NSMidX(visible) - frame.size.width / 2.0;
            frame.origin.y = NSMidY(visible) - frame.size.height / 2.0;
        }

        NSWindowStyleMask style = NSWindowStyleMaskTitled |
                                  NSWindowStyleMaskClosable |
                                  NSWindowStyleMaskResizable |
                                  NSWindowStyleMaskMiniaturizable;
        NSWindow *window = [[NSWindow alloc]
            initWithContentRect:frame
                      styleMask:style
                        backing:NSBackingStoreBuffered
                          defer:NO];
        if (window == nil) {
            fputs("hrt-m6-host: NSWindow allocation failed\n", stderr);
            return 2;
        }

        window.title = title;
        window.releasedWhenClosed = NO;
        window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
                                    NSWindowCollectionBehaviorFullScreenAuxiliary;
        window.backgroundColor = [NSColor colorWithCalibratedRed:0.12
                                                            green:0.15
                                                             blue:0.20
                                                            alpha:1.0];

        NSTextField *label = [NSTextField labelWithString:
            @"Linux guest window operations can be hosted by AppKit."];
        label.textColor = NSColor.whiteColor;
        label.font = [NSFont systemFontOfSize:24.0 weight:NSFontWeightSemibold];
        label.alignment = NSTextAlignmentCenter;
        label.frame = NSMakeRect(40.0, 175.0, 560.0, 70.0);
        [window.contentView addSubview:label];

        [window center];
        [window orderFrontRegardless];
        [window displayIfNeeded];
        [application activateIgnoringOtherApps:YES];
        pump_main_run_loop(0.8);

        const NSInteger number = window.windowNumber;
        const BOOL visible = window.visible;
        const BOOL key = window.keyWindow;
        const BOOL main = window.mainWindow;
        const CGWindowID window_id = number > 0 ? (CGWindowID)number : 0;
        const BOOL listed = window_id != 0 &&
            window_server_contains(window_id, pid, title);
        const BOOL captured = window_id != 0 && capture_window(window_id, argv[1]);

        printf("hrt-m6-host: pid=%d window-number=%ld visible=%d key=%d main=%d "
               "window-server-listed=%d screenshot=%d screen=%d\n",
               (int)pid, (long)number, visible ? 1 : 0, key ? 1 : 0,
               main ? 1 : 0, listed ? 1 : 0, captured ? 1 : 0,
               screen != nil ? 1 : 0);
        fflush(stdout);

        if (number <= 0 || !visible || !listed) {
            fputs("hrt-m6-host: AppKit window did not cross the WindowServer gate\n",
                  stderr);
            [window orderOut:nil];
            [window close];
            return 3;
        }

        puts("HRT M6 HOST: x86_64 AppKit NSWindow is visible in WindowServer");
        fflush(stdout);
        pump_main_run_loop(0.3);
        [window orderOut:nil];
        [window close];
        pump_main_run_loop(0.1);
        return 0;
    }
}
