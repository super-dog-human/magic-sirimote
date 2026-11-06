#include <assert.h>
#include <stdio.h>
#define SIRIMOTE_UNIT_TEST
#define open64 guard_open64
#define ioctl fake_ioctl
#define close fake_close
#include "sirimote_hid_guard.c"
#undef ioctl
#undef close
static unsigned int bus=5, vendor=0x004c, product=0x0266;
static int opens, closes, queries, io_error, open_result=17, last_flags, last_mode;
static int fake_open(const char *path, int flags, ...) {
    (void)path; ++opens; last_flags=flags; last_mode=-1;
    if (flags & O_CREAT) { va_list ap; va_start(ap,flags); last_mode=va_arg(ap,int); va_end(ap); }
    errno=EAGAIN; return open_result;
}
int fake_ioctl(int fd, unsigned long op, ...) {
    assert(fd==17); assert(op==SIRI_RAWINFO); ++queries;
    va_list ap; va_start(ap,op); struct siri_rawinfo *i=va_arg(ap,struct siri_rawinfo*); va_end(ap);
    if(io_error) { errno=io_error; return -1; }
    i->bus=bus; i->vendor=vendor; i->product=product; return 0;
}
int fake_close(int fd) { assert(fd==17); ++closes; errno=EINTR; return -1; }
int main(void) {
    next_open64=fake_open; target_process=1;
    for(int i=0;i<1200;i++) {
        product=i%2 ? 0x0266:0x026d;
        assert(guard_open64("/dev/hidraw64",O_RDWR|O_NONBLOCK)==-1);
        assert(errno==ENODEV);
    }
    assert(opens==1200 && closes==1200 && queries==1200);
    product=0x9999; assert(guard_open64("/dev/hidraw0",O_RDWR)==17); assert(errno==EAGAIN);
    product=0x0266; vendor=0x05ac; assert(guard_open64("/dev/hidraw0",O_RDWR)==17);
    vendor=0x004c; bus=3; assert(guard_open64("/dev/hidraw0",O_RDWR)==17);
    bus=5; io_error=EIO; assert(guard_open64("/dev/hidraw0",O_RDWR)==17); assert(errno==EAGAIN); io_error=0;
    io_error=ENODEV; assert(guard_open64("/dev/hidraw0",O_RDWR)==-1); assert(errno==ENODEV); io_error=0;
    int q=queries;
    const char *paths[]={"/dev/hidraw", "/dev/hidraw0/other", "/dev/hidraw-1", "/tmp/hidraw0", "hidraw0"};
    for(unsigned int i=0;i<sizeof(paths)/sizeof(paths[0]);i++) assert(guard_open64(paths[i],O_RDONLY)==17);
    assert(q==queries);
    target_process=0; assert(guard_open64("/dev/hidraw0",O_RDONLY)==17); assert(q==queries);
    assert(guard_open64("/tmp/example",O_CREAT|O_RDWR,0600)==17); assert(last_mode==0600 && last_flags==(O_CREAT|O_RDWR));
    target_process=1; open_result=-1; assert(guard_open64("/dev/hidraw0",O_RDWR)==-1); assert(errno==EAGAIN && q==queries);
    assert(closes==1201);
    puts("1200 repeated Siri opens released; other devices/processes/paths and open failures preserved.");
    return 0;
}
