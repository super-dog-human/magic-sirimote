/* Prevent LG bthidmanager from retaining Siri Remote hidraw references.
 * Intended only for the reviewed bthidmanager binary; never a global preload.
 * No report reads/writes, device disconnects, background thread, or root API.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stddef.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <unistd.h>

struct siri_rawinfo { unsigned int bus; unsigned short vendor, product; };
_Static_assert(sizeof(struct siri_rawinfo) == 8, "hidraw_info ABI");
#define SIRI_RAWINFO _IOR('H', 0x03, struct siri_rawinfo)
static int (*next_open64)(const char *, int, ...);
static int target_process;

static int hidraw_path(const char *path) {
    if (!path || strncmp(path, "/dev/hidraw", 11)) return 0;
    const unsigned char *s = (const unsigned char *)path + 11;
    if (!*s) return 0;
    for (; *s; ++s) if (*s < '0' || *s > '9') return 0;
    return 1;
}

#ifndef SIRIMOTE_UNIT_TEST
__attribute__((constructor)) static void initialize(void) {
    char path[128];
    next_open64 = (int (*)(const char *, int, ...))dlsym(RTLD_NEXT, "open64");
    ssize_t n = readlink("/proc/self/exe", path, sizeof(path)-1);
    if (n > 0 && n < (ssize_t)sizeof(path)-1) {
        path[n] = 0;
        target_process = !strcmp(path, "/usr/sbin/bthidmanager");
    }
}
#endif

int open64(const char *path, int flags, ...) {
    mode_t mode = 0;
    int needs_mode = !!(flags & O_CREAT);
#ifdef O_TMPFILE
    needs_mode |= ((flags & O_TMPFILE) == O_TMPFILE);
#endif
    if (needs_mode) { va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); }
    if (!next_open64) { errno = ENOSYS; return -1; }
    int fd = needs_mode ? next_open64(path, flags, mode) : next_open64(path, flags);
    int saved_errno = errno;
    if (fd >= 0 && target_process && hidraw_path(path)) {
        struct siri_rawinfo info = {0};
        int metadata = ioctl(fd, SIRI_RAWINFO, &info);
        int disconnected = metadata < 0 && errno == ENODEV;
        int siri = metadata == 0 && info.bus == 5 && info.vendor == 0x004c &&
                   (info.product == 0x0266 || info.product == 0x026d);
        if (siri || disconnected) {
            /* Linux releases the FD even on EINTR. Do not retry close. */
            close(fd);
            errno = ENODEV;
            return -1;
        }
    }
    errno = saved_errno;
    return fd;
}
