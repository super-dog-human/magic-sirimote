"""Run-bound cooperative stop marker. Local filesystem tests are not TV ACL proof."""
import json, math, os, re, secrets, stat, threading, time
from pathlib import Path

def _name(run):
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
 return 'controller-stop-'+run+'.json'

def _directory(path,state_uid,group):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 s=os.fstat(fd)
 if s.st_uid!=state_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in (0o770,0o775):
  os.close(fd);raise RuntimeError('unsafe stop directory')
 return fd

def write_stop(directory,run,process,*,state_uid=5999,group=5000):
 name=_name(run)
 if type(process) is not dict or process.get('pid')!=os.getpid() or type(process.get('startTicks')) is not int or process['startTicks']<=0:raise ValueError('invalid writer process')
 if process.get('status',{}).get('Uid','').split()!=[str(os.getuid())]*4:raise ValueError('writer UID mismatch')
 raw=json.dumps({'schema':1,'run':run,'controllerPid':process['pid'],'controllerStartTicks':process['startTicks']},sort_keys=True).encode()
 d=_directory(directory,state_uid,group);temporary='.'+name+'.'+secrets.token_hex(16)+'.tmp';created=False
 try:
  f=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=d)
  created=True
  try:
   os.fchmod(f,0o640);s=os.fstat(f)
   if s.st_uid!=os.getuid() or s.st_gid!=group or s.st_nlink!=1:raise RuntimeError('unsafe stop writer')
   with os.fdopen(f,'wb') as stream:
    f=None;stream.write(raw);stream.flush();os.fsync(stream.fileno())
   # Publish only the completed, synced inode; link refuses an existing final.
   os.link(temporary,name,src_dir_fd=d,dst_dir_fd=d,follow_symlinks=False)
   os.unlink(temporary,dir_fd=d);created=False;os.fsync(d)
  finally:
   if f is not None:os.close(f)
 finally:
  try:
   if created:os.unlink(temporary,dir_fd=d);os.fsync(d)
  finally:os.close(d)
 return True

def _content_identity(s):
 # link publication followed by temporary unlink changes ctime/nlink only.
 return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns)

def read_stop(directory,run,record,verify_controller,*,state_uid=5999,group=5000):
 """verify_controller must independently check pinned package and exact live PID/startTicks.

 File owner is the kernel-reported writer UID, not proof of a distinct process
 within that UID. Group peers can remove/replace directory entries (denial).
 """
 name=_name(run);p=record['process'];uid=p['status']['Uid'].split()
 if record.get('run')!=run or len(uid)!=4 or len(set(uid))!=1 or not uid[0].isdecimal() or int(uid[0])<=0:raise RuntimeError('invalid controller record')
 d=_directory(directory,state_uid,group)
 try:
  try:f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=d)
  except FileNotFoundError:return False
  try:
   s=os.fstat(f)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink not in (1,2) or s.st_uid!=int(uid[0]) or s.st_gid!=group or stat.S_IMODE(s.st_mode)!=0o640 or not 0<s.st_size<=1024:raise RuntimeError('unsafe stop marker')
   raw=os.read(f,1025);end=os.fstat(f)
   if _content_identity(s)!=_content_identity(end) or end.st_nlink not in (1,2) or len(raw)!=s.st_size:raise RuntimeError('stop marker changed')
  finally:os.close(f)
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate stop key')
    out[k]=v
   return out
  obj=json.loads(raw,object_pairs_hook=unique)
  expected={'schema':1,'run':run,'controllerPid':p['pid'],'controllerStartTicks':p['startTicks']}
  if obj!=expected or any(type(obj[k]) is not type(v) for k,v in expected.items()):raise RuntimeError('stop identity mismatch')
  if verify_controller(record) is not True:raise RuntimeError('live stop writer unconfirmed')
  after=os.stat(name,dir_fd=d,follow_symlinks=False)
  if _content_identity(after)!=_content_identity(s) or after.st_nlink not in (1,2):raise RuntimeError('stop marker replaced')
  return True
 finally:os.close(d)

class StopEvent:
 """Poll through receiver's existing stop_event API; bad IPC triggers cleanup."""
 def __init__(self,local,check,*,clock=time.monotonic,negative_cache_seconds=.05):
  if not callable(clock) or type(negative_cache_seconds) not in (int,float) or not math.isfinite(negative_cache_seconds) or not 0<=negative_cache_seconds<=.05:raise ValueError('invalid stop poll cache')
  self.local=local;self.check=check;self.ipc_error=None;self.clock=clock;self.cache_seconds=negative_cache_seconds;self.negative_at=None;self.last_clock=None
 def is_set(self):
  if self.local.is_set():return True
  try:
   now=self.clock()
   if type(now) not in (int,float) or not math.isfinite(now) or (self.last_clock is not None and now<self.last_clock):raise RuntimeError('invalid monotonic stop clock')
   self.last_clock=now
   if self.negative_at is not None and now-self.negative_at<self.cache_seconds:return False
   # Cache only an exact negative result. Positive/error always re-evaluates.
   self.negative_at=None
   result=self.check()
   if result is False:self.negative_at=now
   elif result is not True:raise RuntimeError('invalid stop poll result')
   return result
  except Exception as exc:self.ipc_error=type(exc).__name__;self.local.set();return True
 def wait(self,timeout=None):
  deadline=None if timeout is None else time.monotonic()+timeout
  while not self.is_set():
   remaining=.05 if deadline is None else min(.05,deadline-time.monotonic())
   if remaining<=0:return False
   self.local.wait(remaining)
  return True
