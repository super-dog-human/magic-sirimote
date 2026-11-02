"""Bounded fixed-vocabulary bootstrap diagnostics; no device operations."""
import json,os,re,stat
ALLOW=re.compile(r'^(?:bootstrap|idle)-[a-z0-9-]{1,64}(?:-(?:RuntimeError|OSError|ValueError|TypeError|AttributeError|FileExistsError|FileNotFoundError|PermissionError|TimeoutError))?$')
class BootTrace:
 def __init__(self):self.events=[]
 def add(self,event):
  if type(event) is str and ALLOW.fullmatch(event) and len(self.events)<32:self.events.append(event)
 def publish(self,dirfd,instance,*,group=5000):
  if type(instance) is not str or re.fullmatch('[0-9a-f]{32}',instance) is None:raise ValueError('invalid instance')
  raw=(json.dumps({'schema':1,'instance':instance,'events':self.events},separators=(',',':'))+'\n').encode()
  if len(raw)>4096:raise ValueError('diagnostic too large')
  fd=os.open('bootstrap-diagnostic-'+instance+'.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=dirfd)
  try:
   os.fchmod(fd,0o640);s=os.fstat(fd)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_gid!=group:raise RuntimeError('diagnostic owner mismatch')
   with os.fdopen(fd,'wb',closefd=False) as f:f.write(raw);f.flush();os.fsync(f.fileno())
  finally:os.close(fd)
  os.fsync(dirfd)
