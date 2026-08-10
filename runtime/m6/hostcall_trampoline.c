#include "appkit_adapter.h"
#include "hostcall_trampoline.h"

#include <stddef.h>
#include <stdio.h>
#include <unistd.h>

_Alignas(16) HrtM6PendingHostcall g_hrt_m6_pending;
_Alignas(16) unsigned char
    g_hrt_m6_hostcall_stack[HRT_M6_HOSTCALL_STACK_SIZE];

_Static_assert(offsetof(HrtM6PendingHostcall, active) == 0u,
               "M6 trampoline active offset");
_Static_assert(offsetof(HrtM6PendingHostcall, guest_gs_base) == 56u,
               "M6 trampoline guest GS offset");
_Static_assert(offsetof(HrtM6PendingHostcall, resume_rip) == 64u,
               "M6 trampoline resume RIP offset");
_Static_assert(offsetof(HrtM6PendingHostcall, resume_rflags) == 72u,
               "M6 trampoline RFLAGS offset");
_Static_assert(offsetof(HrtM6PendingHostcall, guest_rsp) == 80u,
               "M6 trampoline RSP offset");
_Static_assert(offsetof(HrtM6PendingHostcall, guest_rbx) == 88u,
               "M6 trampoline RBX offset");
_Static_assert(offsetof(HrtM6PendingHostcall, guest_r15) == 128u,
               "M6 trampoline R15 offset");
_Static_assert(offsetof(HrtM6PendingHostcall, guest_rdi) == 136u,
               "M6 trampoline RDI offset");
_Static_assert(offsetof(HrtM6PendingHostcall, guest_r9) == 176u,
               "M6 trampoline R9 offset");
_Static_assert(offsetof(HrtM6PendingHostcall, result) == 184u,
               "M6 trampoline result offset");
_Static_assert(offsetof(HrtM6PendingHostcall, fxsave) == 192u,
               "M6 trampoline FXSAVE offset");
_Static_assert(sizeof(HrtM6PendingHostcall) == 704u,
               "M6 trampoline structure size");

void hrt_m6_execute_hostcall(HrtM6PendingHostcall *pending) {
    if (pending != &g_hrt_m6_pending || pending->active != 1u) {
        static const char message[] =
            "hrt-m6: invalid deferred host-call state\n";
        (void)write(STDERR_FILENO, message, sizeof(message) - 1u);
        _exit(125);
    }

    pending->result = hrt_m6_appkit_hostcall(
        pending->opcode,
        pending->argument1,
        pending->argument2,
        pending->argument3,
        pending->argument4,
        pending->argument5);

    fprintf(stderr, "hrt-m6: host-call opcode=%llu result=%lld\n",
            (unsigned long long)pending->opcode,
            (long long)pending->result);
    fflush(stderr);

    pending->active = 0u;
    hrt_m6_resume_guest(pending);
}
