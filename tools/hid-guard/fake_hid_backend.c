/* Test-only ELF interposition backend; never installed in a service. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <fcntl.h>
static int closed, opened, model=0x266;
void guard_test_model(int p) { model=p; }
int guard_test_closed(void) { return closed; }
int guard_test_opened(void) { return opened; }
ssize_t readlink(const char *p,char *buf,size_t n) {
 if(!strcmp(p,"/proc/self/exe")) {
  const char *s="/usr/sbin/bthidmanager";size_t len=strlen(s); if(len>n)len=n;memcpy(buf,s,len);return len;
 }
 return syscall(SYS_readlink,p,buf,n);
}
int open64(const char *p,int flags,...) {
 if(!strcmp(p,"/dev/hidraw9000")) { ++opened;return 12345; }
 int mode=0;if(flags&O_CREAT){va_list a;va_start(a,flags);mode=va_arg(a,int);va_end(a);}
 return syscall(SYS_openat,AT_FDCWD,p,flags,mode);
}
int close(int fd) {if(fd==12345){++closed;return 0;}return syscall(SYS_close,fd);}
int ioctl(int fd,unsigned long op,...) {
 va_list a;va_start(a,op);void *p=va_arg(a,void*);va_end(a);
 if(fd!=12345)return syscall(SYS_ioctl,fd,op,p);
 if(op!=0x80084803UL){errno=EINVAL;return -1;}
 struct {unsigned int bus;unsigned short vendor,product;} *i=p;
 i->bus=5;i->vendor=0x4c;i->product=model;return 0;
}
