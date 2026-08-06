#define _DARWIN_C_SOURCE 1

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef O_DIRECTORY
#define O_DIRECTORY 0x00100000
#endif

#define DARWIN_BSD_CLASS UINT64_C(0x02000000)
#define DARWIN_SYS_GETDIRENTRIES64 UINT64_C(344)
#define DARWIN_DIRENT_HEADER_SIZE 21u
#define LINUX_DIRENT_HEADER_SIZE 19u
#define BUFFER_SIZE 32768u

static int64_t raw_bsd_syscall4(uint64_t number,
                                uint64_t argument1,
                                uint64_t argument2,
                                uint64_t argument3,
                                uint64_t argument4) {
    uint64_t result;
    unsigned char failed;
    __asm__ volatile(
        "movq %[argument4], %%r10\n\t"
        "syscall\n\t"
        "setc %1"
        : "=a"(result), "=qm"(failed)
        : "0"(DARWIN_BSD_CLASS | number),
          "D"(argument1), "S"(argument2), "d"(argument3),
          [argument4] "r"(argument4)
        : "rcx", "r10", "r11", "cc", "memory");
    return failed ? -(int64_t)result : (int64_t)result;
}

static uint16_t load_u16(const unsigned char *source) {
    uint16_t value;
    memcpy(&value, source, sizeof(value));
    return value;
}

static uint64_t load_u64(const unsigned char *source) {
    uint64_t value;
    memcpy(&value, source, sizeof(value));
    return value;
}

static void store_u16(unsigned char *destination, uint16_t value) {
    memcpy(destination, &value, sizeof(value));
}

static void store_u64(unsigned char *destination, uint64_t value) {
    memcpy(destination, &value, sizeof(value));
}

static size_t align_linux_dirent(size_t value) {
    return (value + 7u) & ~(size_t)7u;
}

static uint8_t linux_dirent_type(uint8_t host_type) {
    switch (host_type) {
        case 1u: return 1u;
        case 2u: return 2u;
        case 4u: return 4u;
        case 6u: return 6u;
        case 8u: return 8u;
        case 10u: return 10u;
        case 12u: return 12u;
        default: return 0u;
    }
}

static int contains_name(char names[][1024], size_t count,
                         const char *wanted) {
    for (size_t index = 0u; index < count; ++index) {
        if (strcmp(names[index], wanted) == 0) return 1;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s DIRECTORY\n", argv[0]);
        return 64;
    }

    int fd = open(argv[1], O_RDONLY | O_DIRECTORY);
    if (fd < 0) {
        perror("open probe directory");
        return 1;
    }

    unsigned char host[BUFFER_SIZE];
    unsigned char linux_buffer[BUFFER_SIZE];
    memset(host, 0xa5, sizeof(host));
    memset(linux_buffer, 0, sizeof(linux_buffer));
    off_t position = -1;

    int64_t result = raw_bsd_syscall4(
        DARWIN_SYS_GETDIRENTRIES64, (uint64_t)(unsigned int)fd,
        (uint64_t)(uintptr_t)host, sizeof(host),
        (uint64_t)(uintptr_t)&position);
    printf("probe: raw-result=%" PRId64 " position=%" PRId64 "\n",
           result, (int64_t)position);
    if (result < 0) {
        fprintf(stderr, "probe: raw getdirentries64 errno=%" PRId64 "\n",
                -result);
        close(fd);
        return 2;
    }
    if ((uint64_t)result > sizeof(host)) {
        fprintf(stderr, "probe: oversized Darwin result\n");
        close(fd);
        return 3;
    }

    char names[128][1024];
    size_t name_count = 0u;
    size_t input = 0u;
    size_t output = 0u;
    while (input < (size_t)result) {
        size_t remaining = (size_t)result - input;
        if (remaining < DARWIN_DIRENT_HEADER_SIZE) {
            fprintf(stderr, "probe: short Darwin record tail=%zu\n", remaining);
            return 4;
        }

        const unsigned char *entry = host + input;
        uint64_t inode = load_u64(entry + 0u);
        uint64_t seek = load_u64(entry + 8u);
        uint16_t record = load_u16(entry + 16u);
        uint16_t name_length = load_u16(entry + 18u);
        uint8_t type = entry[20u];
        printf("probe: darwin off=%zu ino=%" PRIu64 " seek=%" PRIu64
               " reclen=%u namlen=%u type=%u name=%.*s\n",
               input, inode, seek, record, name_length, type,
               (int)name_length, (const char *)(entry + 21u));

        if (record < 22u || record > remaining ||
            (size_t)name_length + 21u >= record || name_length >= 1024u) {
            fprintf(stderr, "probe: invalid Darwin record\n");
            return 5;
        }

        if (name_count < 128u) {
            memcpy(names[name_count], entry + 21u, name_length);
            names[name_count][name_length] = '\0';
            ++name_count;
        }

        size_t linux_record = align_linux_dirent(
            LINUX_DIRENT_HEADER_SIZE + (size_t)name_length + 1u);
        if (linux_record > sizeof(linux_buffer) - output) {
            fprintf(stderr, "probe: Linux output overflow\n");
            return 6;
        }
        unsigned char *linux_entry = linux_buffer + output;
        memset(linux_entry, 0, linux_record);
        store_u64(linux_entry + 0u, inode);
        store_u64(linux_entry + 8u, seek != 0u ? seek : (uint64_t)position);
        store_u16(linux_entry + 16u, (uint16_t)linux_record);
        linux_entry[18u] = linux_dirent_type(type);
        memcpy(linux_entry + 19u, entry + 21u, name_length);
        linux_entry[19u + name_length] = '\0';

        input += record;
        output += linux_record;
    }

    printf("probe: converted-bytes=%zu entries=%zu\n", output, name_count);
    if (!contains_name(names, name_count, "libqoffscreen.so") ||
        !contains_name(names, name_count, "libqminimal.so") ||
        !contains_name(names, name_count, "subdir")) {
        fprintf(stderr, "probe: expected names were not enumerated\n");
        return 7;
    }

    size_t cursor = 0u;
    size_t linux_count = 0u;
    while (cursor < output) {
        if (output - cursor < LINUX_DIRENT_HEADER_SIZE) return 8;
        const unsigned char *entry = linux_buffer + cursor;
        uint16_t record = load_u16(entry + 16u);
        if (record < 24u || record > output - cursor) return 9;
        printf("probe: linux off=%zu reclen=%u type=%u name=%s\n",
               cursor, record, entry[18u], (const char *)(entry + 19u));
        cursor += record;
        ++linux_count;
    }

    close(fd);
    if (linux_count != name_count) return 10;
    puts("HRT M5 DIRENTS: Darwin records converted to Linux getdents64 records");
    return 0;
}
