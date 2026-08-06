#define _DARWIN_C_SOURCE 1
#include <inttypes.h>
#include <mach/i386/thread_status.h>
#include <mach/mach.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define FS_MARKER UINT64_C(0x4852544d32465321) /* HRTM2FS! */

static inline uint64_t read_fs_zero(void) {
    uint64_t value;
    __asm__ volatile("movq %%fs:0, %0" : "=r"(value));
    return value;
}

int main(void) {
#if !defined(__x86_64__)
#error "FS thread-state probe must be built as x86_64"
#endif
    mach_port_t thread = mach_thread_self();
    x86_thread_full_state64_t original;
    memset(&original, 0, sizeof(original));
    mach_msg_type_number_t count = x86_THREAD_FULL_STATE64_COUNT;
    kern_return_t result = thread_get_state(
        thread, x86_THREAD_FULL_STATE64,
        (thread_state_t)&original, &count);
    if (result != KERN_SUCCESS) {
        fprintf(stderr, "thread_get_state failed: %d\n", result);
        (void)mach_port_deallocate(mach_task_self(), thread);
        return 1;
    }

    uint64_t marker = FS_MARKER;
    x86_thread_full_state64_t modified = original;
    modified.__fsbase = (uint64_t)(uintptr_t)&marker;
    result = thread_set_state(
        thread, x86_THREAD_FULL_STATE64,
        (thread_state_t)&modified, x86_THREAD_FULL_STATE64_COUNT);
    if (result != KERN_SUCCESS) {
        fprintf(stderr, "thread_set_state FS failed: %d\n", result);
        (void)mach_port_deallocate(mach_task_self(), thread);
        return 2;
    }

    uint64_t observed = read_fs_zero();

    kern_return_t restore_result = thread_set_state(
        thread, x86_THREAD_FULL_STATE64,
        (thread_state_t)&original, x86_THREAD_FULL_STATE64_COUNT);
    (void)mach_port_deallocate(mach_task_self(), thread);
    if (restore_result != KERN_SUCCESS) {
        fprintf(stderr, "thread_set_state restore failed: %d\n",
                restore_result);
        return 3;
    }

    printf("HRT M2 FS state probe: original-fs=0x%016" PRIx64
           " requested-fs=0x%016" PRIxPTR
           " observed=0x%016" PRIx64 "\n",
           original.__fsbase, (uintptr_t)&marker, observed);
    if (observed != FS_MARKER) {
        fprintf(stderr, "HRT M2 FS state probe: direct FS base update failed\n");
        return 4;
    }
    puts("HRT M2 FS state probe: Mach thread_set_state controls FS under Rosetta");
    return 0;
}
