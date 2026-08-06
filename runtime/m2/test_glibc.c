#include <unistd.h>

int main(void) {
    static const char message[] = "HRT M2: glibc reached main\n";
    ssize_t written = write(STDOUT_FILENO, message,
                            sizeof(message) - 1u);
    return written == (ssize_t)(sizeof(message) - 1u) ? 0 : 1;
}
