#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
 void (*model)(int)=dlsym(RTLD_DEFAULT,"guard_test_model");
 int (*closed)(void)=dlsym(RTLD_DEFAULT,"guard_test_closed");
 int (*opened)(void)=dlsym(RTLD_DEFAULT,"guard_test_opened");
 assert(model&&closed&&opened);
 for(int i=0;i<1200;i++){
  model(i%2?0x266:0x26d);errno=0;
  assert(open64("/dev/hidraw9000",O_RDWR|O_NONBLOCK)==-1);assert(errno==ENODEV);
 }
 assert(closed()==1200&&opened()==1200);
 model(0x9999);int fd=open64("/dev/hidraw9000",O_RDWR|O_NONBLOCK);
 assert(fd==12345);assert(closed()==1200);close(fd);assert(closed()==1201);
 puts("Production ELF intercepts versioned open64: 1200 Siri references released, other model preserved.");
 return 0;
}
