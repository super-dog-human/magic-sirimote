"""Keep at most one experimental resident supervisor active per app state."""
import fcntl,os,stat
from pathlib import Path

class SupervisorLease:
 NAME='supervisor.lock'
 def __init__(self,state_path,*,state_uid=5999,group=5000):
  self.dirfd=os.open(Path(state_path),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);self.fd=None
  try:
   s=os.fstat(self.dirfd)
   if (s.st_uid,s.st_gid)!=(state_uid,group) or stat.S_IMODE(s.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe supervisor directory')
   self.directory_identity=(s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))
   fd=os.open(self.NAME,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self.dirfd);self.fd=fd
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or info.st_gid!=group or info.st_size!=0 or stat.S_IMODE(info.st_mode) not in (0o600,0o775):raise RuntimeError('unsafe supervisor lock')
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   # Confirm the open descriptor still names the expected path.
   current=os.stat(self.NAME,dir_fd=self.dirfd,follow_symlinks=False)
   if (current.st_dev,current.st_ino)!=(info.st_dev,info.st_ino):raise RuntimeError('supervisor lock replaced')
   if stat.S_IMODE(info.st_mode)==0o775:
    # webOS can widen app-tree files during a full boot. Repair only our
    # exact empty lock, after obtaining the lock and checking its identity.
    os.fchmod(fd,0o600)
    info=os.fstat(fd);current=os.stat(self.NAME,dir_fd=self.dirfd,follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=0 or
        (info.st_uid,info.st_gid)!=(os.getuid(),group) or stat.S_IMODE(info.st_mode)!=0o600 or
        (current.st_dev,current.st_ino)!=(info.st_dev,info.st_ino)):raise RuntimeError('supervisor lock repair unconfirmed')
   self.identity=(info.st_dev,info.st_ino,info.st_uid,info.st_gid)
  except BaseException:
   self.close();raise
 def held(self):
  if self.fd is None or self.dirfd is None:return False
  try:
   d=os.fstat(self.dirfd)
   if (d.st_dev,d.st_ino,d.st_uid,d.st_gid,stat.S_IMODE(d.st_mode))!=self.directory_identity:return False
   s=os.fstat(self.fd);p=os.stat(self.NAME,dir_fd=self.dirfd,follow_symlinks=False)
   return (stat.S_ISREG(s.st_mode) and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600 and
           (s.st_dev,s.st_ino,s.st_uid,s.st_gid)==self.identity and
           (p.st_dev,p.st_ino,p.st_uid,p.st_gid)==self.identity)
  except OSError:return False
 def close(self):
  if self.fd is not None:os.close(self.fd);self.fd=None
  if self.dirfd is not None:os.close(self.dirfd);self.dirfd=None
