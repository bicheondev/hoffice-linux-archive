#define _DARWIN_C_SOURCE 1
#include "hrt_m2.h"

#include <errno.h>
#include <fcntl.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

static int range_is_free(uintptr_t start, uintptr_t end) {
    mach_vm_address_t address = (mach_vm_address_t)start;
    mach_vm_size_t size = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object_name = MACH_PORT_NULL;
    kern_return_t result = mach_vm_region(
        mach_task_self(), &address, &size, VM_REGION_BASIC_INFO_64,
        (vm_region_info_t)&info, &count, &object_name);
    if (object_name != MACH_PORT_NULL) {
        mach_port_deallocate(mach_task_self(), object_name);
    }
    if (result == KERN_INVALID_ADDRESS) return 1;
    if (result != KERN_SUCCESS) return 0;
    return address >= (mach_vm_address_t)end;
}

static void read_exact(int fd, void *buffer, size_t size, off_t offset) {
    unsigned char *cursor = buffer;
    while (size != 0u) {
        ssize_t count = pread(fd, cursor, size, offset);
        if (count < 0) {
            if (errno == EINTR) continue;
            fatal("pread guest ELF");
        }
        if (count == 0) {
            errno = 0;
            fatal("unexpected end of guest ELF");
        }
        cursor += (size_t)count;
        offset += count;
        size -= (size_t)count;
    }
}

static int host_protection(uint32_t flags) {
    int protection = 0;
    if ((flags & PF_R) != 0u) protection |= PROT_READ;
    if ((flags & PF_W) != 0u) protection |= PROT_WRITE;
    if ((flags & PF_X) != 0u) protection |= PROT_EXEC;
    return protection;
}

size_t patch_syscalls_in_range(void *address, size_t length) {
    unsigned char *bytes = address;
    size_t patched = 0;
    for (size_t index = 0; index + 1u < length; ++index) {
        if (bytes[index] == 0x0f && bytes[index + 1u] == 0x05) {
            bytes[index + 1u] = 0x0b; /* syscall -> ud2 */
            ++patched;
            ++index;
        }
    }
    return patched;
}

static void validate_header(const LoadedElf *loaded) {
    if (memcmp(loaded->header.e_ident, ELFMAG, SELFMAG) != 0 ||
        loaded->header.e_ident[EI_CLASS] != ELFCLASS64 ||
        loaded->header.e_ident[EI_DATA] != ELFDATA2LSB ||
        loaded->header.e_machine != EM_X86_64 ||
        (loaded->header.e_type != ET_DYN && loaded->header.e_type != ET_EXEC) ||
        loaded->header.e_phentsize != sizeof(Elf64_Phdr) ||
        loaded->header.e_phnum == 0 || loaded->header.e_phnum > HRT_MAX_PHDRS) {
        errno = 0;
        fatal("guest must be an x86-64 ET_DYN or ET_EXEC ELF");
    }
}

LoadedElf load_elf_image(const char *path, int require_interpreter) {
    LoadedElf loaded;
    memset(&loaded, 0, sizeof(loaded));

    int fd = open(path, O_RDONLY);
    if (fd < 0) fatal_detail("open guest ELF", path);

    read_exact(fd, &loaded.header, sizeof(loaded.header), 0);
    validate_header(&loaded);
    read_exact(fd, loaded.phdrs,
               (size_t)loaded.header.e_phnum * sizeof(Elf64_Phdr),
               (off_t)loaded.header.e_phoff);

    uintptr_t minimum = UINTPTR_MAX;
    uintptr_t maximum = 0;
    const Elf64_Phdr *interp_phdr = NULL;
    for (uint16_t index = 0; index < loaded.header.e_phnum; ++index) {
        const Elf64_Phdr *phdr = &loaded.phdrs[index];
        if (phdr->p_type == PT_INTERP) interp_phdr = phdr;
        if (phdr->p_type != PT_LOAD || phdr->p_memsz == 0) continue;
        if (phdr->p_vaddr + phdr->p_memsz < phdr->p_vaddr) {
            errno = 0;
            fatal("overflowing PT_LOAD range");
        }
        uintptr_t start = align_down((uintptr_t)phdr->p_vaddr, g_page_size);
        uintptr_t end = align_up(
            (uintptr_t)(phdr->p_vaddr + phdr->p_memsz), g_page_size);
        if (start < minimum) minimum = start;
        if (end > maximum) maximum = end;
    }
    if (minimum == UINTPTR_MAX || maximum <= minimum) {
        errno = 0;
        fatal("ELF has no usable PT_LOAD segments");
    }

    if (interp_phdr != NULL) {
        if (interp_phdr->p_filesz < 2u ||
            interp_phdr->p_filesz > HRT_MAX_INTERP_PATH) {
            errno = 0;
            fatal("invalid PT_INTERP size");
        }
        read_exact(fd, loaded.interpreter, (size_t)interp_phdr->p_filesz,
                   (off_t)interp_phdr->p_offset);
        loaded.interpreter[HRT_MAX_INTERP_PATH - 1u] = '\0';
        if (loaded.interpreter[interp_phdr->p_filesz - 1u] != '\0' ||
            loaded.interpreter[0] != '/') {
            errno = 0;
            fatal("PT_INTERP must be an absolute NUL-terminated path");
        }
    }
    if (require_interpreter && loaded.interpreter[0] == '\0') {
        errno = 0;
        fatal("main ELF has no PT_INTERP");
    }
    if (!require_interpreter && loaded.interpreter[0] != '\0') {
        errno = 0;
        fatal("nested PT_INTERP is not supported");
    }

    size_t span = (size_t)(maximum - minimum);
    void *mapping;
    if (loaded.header.e_type == ET_DYN) {
        mapping = mmap(NULL, span, PROT_READ | PROT_WRITE | PROT_EXEC,
                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (mapping == MAP_FAILED) fatal("mmap ET_DYN image");
        loaded.load_bias = (uintptr_t)mapping - minimum;
    } else {
        if (minimum < g_page_size || !range_is_free(minimum, maximum)) {
            errno = 0;
            fatal("ET_EXEC PT_LOAD range is unavailable on macOS");
        }
        mapping = mmap((void *)minimum, span,
                       PROT_READ | PROT_WRITE | PROT_EXEC,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0);
        if (mapping == MAP_FAILED || (uintptr_t)mapping != minimum) {
            fatal("mmap ET_EXEC image");
        }
        loaded.load_bias = 0;
    }
    memset(mapping, 0, span);

    for (uint16_t index = 0; index < loaded.header.e_phnum; ++index) {
        const Elf64_Phdr *phdr = &loaded.phdrs[index];
        if (phdr->p_type == PT_PHDR) {
            loaded.phdr_address = loaded.load_bias + (uintptr_t)phdr->p_vaddr;
        }
        if (phdr->p_type != PT_LOAD || phdr->p_memsz == 0) continue;
        if (phdr->p_filesz > phdr->p_memsz) {
            errno = 0;
            fatal("PT_LOAD filesz exceeds memsz");
        }
        uintptr_t destination = loaded.load_bias + (uintptr_t)phdr->p_vaddr;
        if (phdr->p_filesz != 0) {
            read_exact(fd, (void *)destination,
                       (size_t)phdr->p_filesz, (off_t)phdr->p_offset);
        }
        if ((phdr->p_flags & PF_X) != 0u) {
            loaded.patched_syscalls += patch_syscalls_in_range(
                (void *)destination, (size_t)phdr->p_filesz);
        }
        if (loaded.phdr_address == 0 &&
            loaded.header.e_phoff >= phdr->p_offset &&
            loaded.header.e_phoff +
                (uint64_t)loaded.header.e_phnum * sizeof(Elf64_Phdr) <=
                phdr->p_offset + phdr->p_filesz) {
            loaded.phdr_address = destination +
                (uintptr_t)(loaded.header.e_phoff - phdr->p_offset);
        }
    }
    if (loaded.phdr_address == 0) {
        errno = 0;
        fatal("ELF program headers are not mapped");
    }

    for (uint16_t index = 0; index < loaded.header.e_phnum; ++index) {
        const Elf64_Phdr *phdr = &loaded.phdrs[index];
        if (phdr->p_type != PT_LOAD || phdr->p_memsz == 0) continue;
        uintptr_t start = align_down(
            loaded.load_bias + (uintptr_t)phdr->p_vaddr, g_page_size);
        uintptr_t end = align_up(
            loaded.load_bias + (uintptr_t)(phdr->p_vaddr + phdr->p_memsz),
            g_page_size);
        if (mprotect((void *)start, end - start,
                     host_protection(phdr->p_flags)) != 0) {
            fatal("mprotect guest segment");
        }
    }

    close(fd);
    loaded.image_start = (uintptr_t)mapping;
    loaded.image_end = loaded.image_start + span;
    loaded.entry = loaded.load_bias + (uintptr_t)loaded.header.e_entry;
    return loaded;
}
