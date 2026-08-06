#include <stddef.h>
#include <unistd.h>

int main(void) {
    static const char message[] =
        "HRT M2: real ld-linux and glibc reached the dynamic main program\n";
    const size_t length = sizeof(message) - 1u;
    const ssize_t written = write(STDOUT_FILENO, message, length);
    return written == (ssize_t)length ? 0 : 1;
}
