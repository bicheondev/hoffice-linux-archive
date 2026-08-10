#include <stdint.h>
#include <stdlib.h>
#include <sys/random.h>
#include <time.h>
#include <unistd.h>

static __thread uint64_t tls_marker = UINT64_C(0x4852544d33474c42);

int main(void) {
    static const char message[] =
        "HRT M3: real glibc loader, malloc, TLS, time and random passed\n";

    if (tls_marker != UINT64_C(0x4852544d33474c42)) return 81;
    tls_marker ^= UINT64_C(0x00000000000000ff);
    if (tls_marker != UINT64_C(0x4852544d33474cbd)) return 82;

    unsigned char *allocation = malloc(4096u);
    if (allocation == NULL) return 83;
    for (size_t index = 0u; index < 4096u; ++index) {
        allocation[index] = (unsigned char)(index ^ 0x5au);
    }

    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return 84;
    if (now.tv_sec < 0 || now.tv_nsec < 0 || now.tv_nsec >= 1000000000L) {
        return 85;
    }

    uint64_t random_value = 0u;
    if (getrandom(&random_value, sizeof(random_value), 0) !=
        (ssize_t)sizeof(random_value)) {
        return 86;
    }
    if (getpid() <= 0) return 87;

    free(allocation);
    if (write(STDOUT_FILENO, message, sizeof(message) - 1u) !=
        (ssize_t)(sizeof(message) - 1u)) {
        return 88;
    }
    return 0;
}
