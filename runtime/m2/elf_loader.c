#define _DARWIN_C_SOURCE 1
#include "glibc_host.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

static int range_within_file(uint64_t offset, uint64_t size,
                             uint64_t file_size) {
    return offset <= file_size && size <= file_size - offset;
}

static void read_exact(int fd, void *buffer, size_t size, off_t offset) {
    unsigned char *cursor = (unsigned char *)buffer;
    while (size != 0u) {
        ssize_t count = pread(fd, cursor, size, offset);
        if (count < 0) {
            if (errno == EINTR) continue;
            hrt_fatal("pread initial ELF image");
        }
        if (count == 0) {
            errno = 0;
            hrt_fatal("unexpected end of initial ELF image");
        }
        cursor += (size_t)count;
        offset += count;
        size -= (size_t)count;
    }
}

static void copy_path(char destination[PATH_MAX], const char *source,
                      const char *description) {
    int written = snprintf(destination, PATH_MAX, "%s", source);
    if (written < 0 || written >= PATH_MAX) {
        errno = 0;
        hrt_fatal(description);
    }
}

HrtLoadedImage hrt_load_initial_elf(const char *host_path,
                                    const char *guest_path,
                                    int permit_interpreter) {
    HrtLoadedImage image;
    memset(&image, 0, sizeof(image));
    copy_path(image.host_path, host_path, "host ELF path is too long");
    copy_path(image.guest_path, guest_path, "guest ELF path is too long");

    int fd = open(host_path, O_RDONLY);
    if (fd < 0) hrt_fatal("open initial ELF image");

    struct stat status;
    if (fstat(fd, &status) != 0) hrt_fatal("fstat initial ELF image");
    if (status.st_size < (off_t)sizeof(HrtElf64Ehdr)) {
        errno = 0;
        hrt_fatal("initial ELF is shorter than its header");
    }
    uint64_t file_size = (uint64_t)status.st_size;

    read_exact(fd, &image.header, sizeof(image.header), 0);
    if (memcmp(image.header.e_ident, HRT_ELFMAG, HRT_SELFMAG) != 0 ||
        image.header.e_ident[HRT_ELF_EI_CLASS] != HRT_ELFCLASS64 ||
        image.header.e_ident[HRT_ELF_EI_DATA] != HRT_ELFDATA2LSB ||
        image.header.e_ident[HRT_ELF_EI_VERSION] != HRT_EV_CURRENT ||
        image.header.e_version != HRT_EV_CURRENT ||
        image.header.e_machine != HRT_EM_X86_64 ||
        image.header.e_type != HRT_ET_DYN ||
        image.header.e_phentsize != sizeof(HrtElf64Phdr) ||
        image.header.e_phnum == 0 ||
        image.header.e_phnum > HRT_M2_MAX_PHDRS) {
        errno = 0;
        hrt_fatal("M2 currently requires a Linux x86-64 ET_DYN image");
    }

    uint64_t phdr_bytes =
        (uint64_t)image.header.e_phnum * (uint64_t)sizeof(HrtElf64Phdr);
    if (!range_within_file(image.header.e_phoff, phdr_bytes, file_size)) {
        errno = 0;
        hrt_fatal("initial ELF program headers are outside the file");
    }
    read_exact(fd, image.phdrs, (size_t)phdr_bytes,
               (off_t)image.header.e_phoff);

    uintptr_t minimum = UINTPTR_MAX;
    uintptr_t maximum = 0;
    for (uint16_t index = 0; index < image.header.e_phnum; ++index) {
        const HrtElf64Phdr *phdr = &image.phdrs[index];
        if (phdr->p_type != HRT_PT_LOAD || phdr->p_memsz == 0u) continue;
        if (phdr->p_vaddr > UINT64_MAX - phdr->p_memsz) {
            errno = 0;
            hrt_fatal("initial ELF PT_LOAD address overflow");
        }
        uintptr_t start = hrt_align_down(
            (uintptr_t)phdr->p_vaddr, g_host_page_size);
        uintptr_t end = hrt_align_up(
            (uintptr_t)(phdr->p_vaddr + phdr->p_memsz),
            g_host_page_size);
        if (start < minimum) minimum = start;
        if (end > maximum) maximum = end;
    }
    if (minimum == UINTPTR_MAX || maximum <= minimum) {
        errno = 0;
        hrt_fatal("initial ELF has no valid PT_LOAD span");
    }

    size_t span = maximum - minimum;
    void *mapping = mmap(NULL, span,
                         PROT_READ | PROT_WRITE | PROT_EXEC,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (mapping == MAP_FAILED) hrt_fatal("mmap initial ELF image");
    image.image_start = (uintptr_t)mapping;
    image.image_end = image.image_start + span;
    image.load_bias = image.image_start - minimum;

    for (uint16_t index = 0; index < image.header.e_phnum; ++index) {
        const HrtElf64Phdr *phdr = &image.phdrs[index];

        if (phdr->p_type == HRT_PT_INTERP) {
            if (!permit_interpreter) {
                errno = 0;
                hrt_fatal("the Linux interpreter contains PT_INTERP");
            }
            if (phdr->p_filesz < 2u ||
                phdr->p_filesz > (uint64_t)PATH_MAX ||
                !range_within_file(phdr->p_offset, phdr->p_filesz,
                                   file_size)) {
                errno = 0;
                hrt_fatal("invalid PT_INTERP string");
            }
            read_exact(fd, image.interpreter, (size_t)phdr->p_filesz,
                       (off_t)phdr->p_offset);
            if (image.interpreter[phdr->p_filesz - 1u] != '\0') {
                errno = 0;
                hrt_fatal("PT_INTERP is not NUL terminated");
            }
            continue;
        }

        if (phdr->p_type == HRT_PT_PHDR) {
            image.phdr_address = image.load_bias + (uintptr_t)phdr->p_vaddr;
            continue;
        }

        if (phdr->p_type != HRT_PT_LOAD || phdr->p_memsz == 0u) continue;
        if (phdr->p_filesz > phdr->p_memsz ||
            !range_within_file(phdr->p_offset, phdr->p_filesz,
                               file_size)) {
            errno = 0;
            hrt_fatal("invalid initial ELF PT_LOAD file range");
        }

        uintptr_t destination = image.load_bias + (uintptr_t)phdr->p_vaddr;
        if (destination < image.image_start ||
            destination > image.image_end ||
            phdr->p_memsz > image.image_end - destination) {
            errno = 0;
            hrt_fatal("initial ELF PT_LOAD is outside its mapping");
        }
        if (phdr->p_filesz != 0u) {
            read_exact(fd, (void *)destination, (size_t)phdr->p_filesz,
                       (off_t)phdr->p_offset);
        }
        if ((phdr->p_flags & HRT_PF_X) != 0u) {
            image.patched_syscalls += hrt_patch_linux_syscalls(
                (unsigned char *)destination, (size_t)phdr->p_filesz);
        }

        uint64_t phdr_file_end =
            image.header.e_phoff +
            (uint64_t)image.header.e_phnum * sizeof(HrtElf64Phdr);
        uint64_t segment_file_end = phdr->p_offset + phdr->p_filesz;
        if (image.phdr_address == 0u &&
            image.header.e_phoff >= phdr->p_offset &&
            phdr_file_end <= segment_file_end) {
            image.phdr_address =
                image.load_bias + (uintptr_t)phdr->p_vaddr +
                (uintptr_t)(image.header.e_phoff - phdr->p_offset);
        }
    }

    if (image.phdr_address == 0u) {
        errno = 0;
        hrt_fatal("could not locate initial ELF program headers in memory");
    }
    image.entry_address = image.load_bias + (uintptr_t)image.header.e_entry;
    if (image.entry_address < image.image_start ||
        image.entry_address >= image.image_end) {
        errno = 0;
        hrt_fatal("initial ELF entry point is outside its mapping");
    }

    for (uint16_t index = 0; index < image.header.e_phnum; ++index) {
        const HrtElf64Phdr *phdr = &image.phdrs[index];
        if (phdr->p_type != HRT_PT_LOAD || phdr->p_memsz == 0u) continue;
        uintptr_t start = hrt_align_down(
            image.load_bias + (uintptr_t)phdr->p_vaddr,
            g_host_page_size);
        uintptr_t end = hrt_align_up(
            image.load_bias +
                (uintptr_t)(phdr->p_vaddr + phdr->p_memsz),
            g_host_page_size);
        uint32_t linux_protection = 0;
        if ((phdr->p_flags & HRT_PF_R) != 0u) {
            linux_protection |= LINUX_PROT_READ;
        }
        if ((phdr->p_flags & HRT_PF_W) != 0u) {
            linux_protection |= LINUX_PROT_WRITE;
        }
        if ((phdr->p_flags & HRT_PF_X) != 0u) {
            linux_protection |= LINUX_PROT_EXEC;
        }
        if (mprotect((void *)start, end - start,
                     hrt_host_protection(linux_protection)) != 0) {
            hrt_fatal("mprotect initial ELF segment");
        }
    }

    if (close(fd) != 0) hrt_fatal("close initial ELF image");
    return image;
}
