#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv) {
 if(argc!=2)return 2;
 write(2,"before-dlopen\n",14);
 void *h=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
 if(!h){const char *error=dlerror(); write(2,error,strlen(error));return 3;}
 write(2,"after-dlopen\n",13);
 int (*fn)(const char *,int,...)=dlsym(h,"open64");
 if(!fn)return 4;
 write(2,"after-dlsym\n",12);
 int fd=fn("/dev/null",O_RDONLY|O_CLOEXEC);
 write(2,"after-open\n",11);
 if(fd<0)return 5;
 close(fd);
 errno=0;
 if(fn("/sirimote-guard-intentionally-missing",O_RDONLY)!=-1 || errno!=ENOENT)return 6;
 puts("{\"loader\":true,\"passthrough\":true,\"errnoPreserved\":true}");
 return 0;
}
