#define _DARWIN_C_SOURCE 1
#include "hrt_m0.h"

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

static size_t patch_syscalls(unsigned char *start, size_t length) {
    size_t patched = 0;
    for (size_t index = 0; index + 1u < length; ++index) {
        if (start[index] == 0x0f && start[index + 1u] == 0x05) {
            start[index + 1u] = 0x0b; /* syscall -> ud2 */
            ++patched;
            ++index;
        }
    }
    return patched;
}

static void *allocate_image(uint16_t elf_type, uintptr_t minimum,
                            uintptr_t maximum, uintptr_t *load_bias) {
    size_t span = (size_t)(maximum - minimum);
    int flags = MAP_PRIVATE | MAP_ANONYMOUS;
    void *requested = NULL;

    if (elf_type == ET_EXEC) {
        if (!range_is_free(minimum, maximum)) {
            errno = 0;
            fatal("guest PT_LOAD range collides with Mach-O host");
        }
        requested = (void *)minimum;
        flags |= MAP_FIXED;
    }

    void *mapping = mmap(requested, span, PROT_READ | PROT_WRITE,
                         flags, -1, 0);
    if (mapping == MAP_FAILED) fatal("mmap guest image");
    if (elf_type == ET_EXEC && (uintptr_t)mapping != minimum) {
        errno = 0;
        fatal("fixed ET_EXEC mapping returned the wrong address");
    }

    *load_bias = (uintptr_t)mapping - minimum;
    memset(mapping, 0, span);
    return mapping;
}

LoadedElf load_elf(const char *path) {
    LoadedElf loaded;
    memset(&loaded, 0, sizeof(loaded));
    int fd = open(path, O_RDONLY);
    if (fd < 0) fatal("open guest ELF");

    read_exact(fd, &loaded.header, sizeof(loaded.header), 0);
    if (memcmp(loaded.header.e_ident, ELFMAG, SELFMAG) != 0 ||
        loaded.header.e_ident[EI_CLASS] != ELFCLASS64 ||
        loaded.header.e_ident[EI_DATA] != ELFDATA2LSB ||
        loaded.header.e_machine != EM_X86_64 ||
        (loaded.header.e_type != ET_EXEC && loaded.header.e_type != ET_DYN) ||
        loaded.header.e_phentsize != sizeof(Elf64_Phdr) ||
        loaded.header.e_phnum == 0 || loaded.header.e_phnum > HRT_MAX_PHDRS) {
        errno = 0;
        fatal("guest must be an x86-64 ET_EXEC or ET_DYN ELF");
    }
    read_exact(fd, loaded.phdrs,
               (size_t)loaded.header.e_phnum * sizeof(Elf64_Phdr),
               (off_t)loaded.header.e_phoff);

    uintptr_t minimum = UINTPTR_MAX;
    uintptr_t maximum = 0;
    for (uint16_t index = 0; index < loaded.header.e_phnum; ++index) {
        const Elf64_Phdr *phdr = &loaded.phdrs[index];
        if (phdr->p_type != PT_LOAD || phdr->p_memsz == 0) continue;
        if (phdr->p_vaddr > UINTPTR_MAX - phdr->p_memsz) {
            errno = 0;
            fatal("PT_LOAD address overflow");
        }
        uintptr_t start = align_down((uintptr_t)phdr->p_vaddr, g_page_size);
        uintptr_t end = align_up((uintptr_t)(phdr->p_vaddr + phdr->p_memsz), g_page_size);
        if (start < minimum) minimum = start;
        if (end > maximum) maximum = end;
    }
    if (minimum == UINTPTR_MAX || maximum <= minimum ||
        (loaded.header.e_type == ET_EXEC && minimum < g_page_size)) {
        errno = 0;
        fatal("invalid PT_LOAD range");
    }

    void *mapping = allocate_image(loaded.header.e_type, minimum, maximum,
                                   &loaded.load_bias);
    size_t span = (size_t)(maximum - minimum);

    for (uint16_t index = 0; index < loaded.header.e_phnum; ++index) {
        const Elf64_Phdr *phdr = &loaded.phdrs[index];
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
            loaded.patched_syscalls += patch_syscalls(
                (unsigned char *)destination, (size_t)phdr->p_filesz);
        }
        if (loaded.header.e_phoff >= phdr->p_offset &&
            loaded.header.e_phoff +
                (uint64_t)loaded.header.e_phnum * sizeof(Elf64_Phdr) <=
                phdr->p_offset + phdr->p_filesz) {
            loaded.phdr_address = destination +
                (uintptr_t)(loaded.header.e_phoff - phdr->p_offset);
        }
    }

    if (mprotect(mapping, span, PROT_NONE) != 0) fatal("mprotect guest image guard");
    for (uint16_t index = 0; index < loaded.header.e_phnum; ++index) {
        const Elf64_Phdr *phdr = &loaded.phdrs[index];
        if (phdr->p_type != PT_LOAD || phdr->p_memsz == 0) continue;
        uintptr_t start = loaded.load_bias +
            align_down((uintptr_t)phdr->p_vaddr, g_page_size);
        uintptr_t end = loaded.load_bias +
            align_up((uintptr_t)(phdr->p_vaddr + phdr->p_memsz), g_page_size);
        if (mprotect((void *)start, end - start,
                     host_protection(phdr->p_flags)) != 0) {
            fatal("mprotect guest segment");
        }
    }

    close(fd);
    loaded.image_start = (uintptr_t)mapping;
    loaded.image_end = loaded.image_start + span;
    loaded.entry_address = loaded.load_bias + (uintptr_t)loaded.header.e_entry;
    if (loaded.entry_address < loaded.image_start ||
        loaded.entry_address >= loaded.image_end) {
        errno = 0;
        fatal("ELF entry point lies outside the mapped image");
    }
    return loaded;
}
