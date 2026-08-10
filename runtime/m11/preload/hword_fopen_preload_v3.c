#define _GNU_SOURCE 1

#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define HRT_PRELOAD_MAX_SUBSTITUTIONS 3u
#define HRT_EXPORT __attribute__((visibility("default")))

static const char hrt_blank_template[] =
    "/tmp/hrt-home/.hnc/User/Hword/Template/ko-KR/Document[0].hwdt";
static const char hrt_hoffice_prefix[] = "/opt/hnc/hoffice11/";
static unsigned int hrt_substitution_count;
static unsigned int hrt_empty_observation_count;
static _Thread_local int hrt_resolving;

typedef FILE *(*hrt_fopen_type)(const char *, const char *);

typedef struct {
    int resolved;
    int is_hoffice;
    const char *object;
    uintptr_t offset;
} HrtCaller;

static size_t hrt_append_literal(char *buffer, size_t cursor, size_t capacity,
                                 const char *value)
{
    if (buffer == NULL || value == NULL || capacity == 0u)
        return cursor;
    while (*value != '\0' && cursor < capacity)
        buffer[cursor++] = *value++;
    return cursor;
}

static size_t hrt_append_decimal(char *buffer, size_t cursor, size_t capacity,
                                 uintptr_t value)
{
    char digits[3u * sizeof(uintptr_t) + 1u];
    size_t count = 0u;
    do {
        digits[count++] = (char)('0' + (value % 10u));
        value /= 10u;
    } while (value != 0u && count < sizeof(digits));
    while (count != 0u && cursor < capacity)
        buffer[cursor++] = digits[--count];
    return cursor;
}

static size_t hrt_append_hex(char *buffer, size_t cursor, size_t capacity,
                             uintptr_t value)
{
    static const char digits[] = "0123456789abcdef";
    cursor = hrt_append_literal(buffer, cursor, capacity, "0x");
    int started = 0;
    for (int shift = (int)(sizeof(value) * 8u) - 4; shift >= 0; shift -= 4) {
        const unsigned int digit = (unsigned int)((value >> shift) & 0xfu);
        if (!started && digit == 0u && shift != 0)
            continue;
        started = 1;
        if (cursor < capacity)
            buffer[cursor++] = digits[digit];
    }
    return cursor;
}

static void hrt_write_all(const char *buffer, size_t size)
{
    while (size != 0u) {
        const ssize_t result = write(STDERR_FILENO, buffer, size);
        if (result > 0) {
            buffer += (size_t)result;
            size -= (size_t)result;
            continue;
        }
        if (result < 0 && errno == EINTR)
            continue;
        break;
    }
}

static int hrt_starts_with(const char *value, const char *prefix)
{
    if (value == NULL || prefix == NULL)
        return 0;
    while (*prefix != '\0') {
        if (*value++ != *prefix++)
            return 0;
    }
    return 1;
}

static HrtCaller hrt_caller(void *return_address)
{
    HrtCaller caller;
    memset(&caller, 0, sizeof(caller));
    caller.object = "(unresolved)";
    Dl_info info;
    memset(&info, 0, sizeof(info));
    if (dladdr(return_address, &info) == 0)
        return caller;
    caller.resolved = 1;
    caller.object = info.dli_fname != NULL ? info.dli_fname : "(unnamed)";
    if (info.dli_fbase != NULL)
        caller.offset = (uintptr_t)return_address - (uintptr_t)info.dli_fbase;
    caller.is_hoffice = hrt_starts_with(caller.object, hrt_hoffice_prefix);
    return caller;
}

static void hrt_log_event(const char *symbol, const char *mode,
                          unsigned int observation, unsigned int index,
                          int eligible, int applied, int template_ready,
                          const char *reason, void *return_address,
                          HrtCaller caller)
{
    char buffer[1280];
    size_t cursor = 0u;
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer),
                                "HRT M11 PRELOAD_FOPEN_V3: symbol=");
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), symbol);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer),
                                " observation=");
    cursor = hrt_append_decimal(buffer, cursor, sizeof(buffer), observation);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), " index=");
    cursor = hrt_append_decimal(buffer, cursor, sizeof(buffer), index);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), " eligible=");
    cursor = hrt_append_decimal(buffer, cursor, sizeof(buffer),
                                eligible != 0 ? 1u : 0u);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), " applied=");
    cursor = hrt_append_decimal(buffer, cursor, sizeof(buffer),
                                applied != 0 ? 1u : 0u);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer),
                                " template-ready=");
    cursor = hrt_append_decimal(buffer, cursor, sizeof(buffer),
                                template_ready != 0 ? 1u : 0u);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), " mode=");
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer),
                                mode != NULL ? mode : "(null)");
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), " reason=");
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), reason);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), " caller=");
    cursor = hrt_append_hex(buffer, cursor, sizeof(buffer),
                            (uintptr_t)return_address);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer),
                                " caller-object=");
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer), caller.object);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer),
                                " caller-offset=");
    cursor = hrt_append_hex(buffer, cursor, sizeof(buffer), caller.offset);
    cursor = hrt_append_literal(buffer, cursor, sizeof(buffer),
                                " replacement=Document[0].hwdt\n");
    hrt_write_all(buffer, cursor);
}

static int hrt_read_only_mode(const char *mode)
{
    if (mode == NULL || mode[0] == '\0')
        return 0;
    for (const char *cursor = mode; *cursor != '\0'; ++cursor) {
        if (*cursor == 'w' || *cursor == 'a' || *cursor == '+')
            return 0;
    }
    return 1;
}

static hrt_fopen_type hrt_resolve(const char *symbol)
{
    if (hrt_resolving != 0)
        return NULL;
    hrt_resolving = 1;
    dlerror();
    void *address = dlsym(RTLD_NEXT, symbol);
    hrt_fopen_type function = NULL;
    if (sizeof(function) == sizeof(address))
        memcpy(&function, &address, sizeof(function));
    hrt_resolving = 0;
    return function;
}

static FILE *hrt_dispatch(const char *symbol, const char *filename,
                          const char *mode, void *return_address)
{
    hrt_fopen_type real_function = hrt_resolve(symbol);
    if (real_function == NULL && strcmp(symbol, "fopen64") == 0)
        real_function = hrt_resolve("fopen");
    if (real_function == NULL) {
        errno = ENOSYS;
        return NULL;
    }
    if (filename == NULL || filename[0] != '\0' || !hrt_read_only_mode(mode))
        return real_function(filename, mode);

    const unsigned int observation = __atomic_add_fetch(
        &hrt_empty_observation_count, 1u, __ATOMIC_RELAXED);
    const HrtCaller caller = hrt_caller(return_address);
    const int template_ready = access(hrt_blank_template, R_OK) == 0;
    const int eligible = caller.is_hoffice && template_ready;
    unsigned int index = 0u;
    int applied = 0;
    const char *reason = "eligible";
    if (!caller.resolved)
        reason = "caller-unresolved";
    else if (!caller.is_hoffice)
        reason = "caller-not-hoffice";
    else if (!template_ready)
        reason = "template-not-ready";
    else {
        index = __atomic_add_fetch(
            &hrt_substitution_count, 1u, __ATOMIC_RELAXED);
        applied = index <= HRT_PRELOAD_MAX_SUBSTITUTIONS;
        if (!applied)
            reason = "substitution-limit";
    }
    hrt_log_event(symbol, mode, observation, index, eligible, applied,
                  template_ready, reason, return_address, caller);
    return real_function(applied ? hrt_blank_template : filename, mode);
}

HRT_EXPORT FILE *fopen(const char *filename, const char *mode)
{
    return hrt_dispatch("fopen", filename, mode,
                        __builtin_return_address(0));
}

HRT_EXPORT FILE *fopen64(const char *filename, const char *mode)
{
    return hrt_dispatch("fopen64", filename, mode,
                        __builtin_return_address(0));
}

__attribute__((constructor))
static void hrt_preload_constructor(void)
{
    static const char marker[] =
        "HRT M11 PRELOAD_FOPEN_V3: loaded=1 scope=ready-hoffice-callers target=Document[0].hwdt\n";
    hrt_write_all(marker, sizeof(marker) - 1u);
}
