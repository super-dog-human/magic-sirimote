"""One durable TV-local receiver launch intent; no launch or input itself.

This record does not prove a launch outcome and has no automatic reclamation.
Caller must hold the supervisor lease. Existing records block a new attempt.
"""
import json,os,re,stat
from pathlib import Path
class ReceiverLaunchIntent:
 NAME='receiver-launch-intent.json'
 def __init__(self,directory,run,*,state_uid=5999,group=5000):
  if type(run) is not str or not re.fullmatch('[0-9a-f]{32}',run):raise ValueError('invalid run')
  self.run=run;self.fd=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);self.used=False
  try:
   s=os.fstat(self.fd)
   if not stat.S_ISDIR(s.st_mode) or s.st_uid!=state_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe state directory')
   self.identity=(s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode));self.owner=os.getuid();self.group=group
  except BaseException:os.close(self.fd);self.fd=None;raise
 def __call__(self,event):
  if self.used or self.fd is None:raise RuntimeError('intent already used')
  if type(event) is not dict or set(event)!={'stage','run','generation'} or event['stage']!='receiver-launch-intent' or event['run']!=self.run or type(event['generation']) is not int or event['generation']<=0:raise ValueError('invalid launch intent')
  self.used=True
  s=os.fstat(self.fd)
  if (s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=self.identity:raise RuntimeError('state changed')
  f=os.open(self.NAME,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=self.fd)
  try:
   os.fchmod(f,0o640);info=os.fstat(f)
   if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=self.owner or info.st_gid!=self.group:raise RuntimeError('unsafe intent file')
   with os.fdopen(f,'wb') as stream:
    f=None;stream.write((json.dumps(event,sort_keys=True,separators=(',',':'))+'\n').encode());stream.flush();os.fsync(stream.fileno())
   os.fsync(self.fd);self.file_identity=(info.st_dev,info.st_ino,info.st_uid,info.st_gid);self.event=dict(event);return True
  finally:
   if f is not None:os.close(f)
 def archive_completed(self,result,*,independent_proof):
  if self.fd is None or not self.used or not hasattr(self,'file_identity') or type(result) is not dict or result.get('run')!=self.run or result.get('status')!='complete' or result.get('sensorStopVerified') is not True or result.get('journalArchived') is not True or not callable(independent_proof) or independent_proof() is not True:raise RuntimeError('launch completion unverified')
  before=os.stat(self.NAME,dir_fd=self.fd,follow_symlinks=False)
  if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o640 or (before.st_dev,before.st_ino,before.st_uid,before.st_gid)!=self.file_identity or before.st_size>4096:raise RuntimeError('intent changed')
  f=os.open(self.NAME,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self.fd)
  try:
   info=os.fstat(f);raw=os.read(f,4097)
   if (info.st_dev,info.st_ino,info.st_uid,info.st_gid)!=self.file_identity or len(raw)!=before.st_size or json.loads(raw)!=self.event:raise RuntimeError('intent contents changed')
  finally:os.close(f)
  if independent_proof() is not True:raise RuntimeError('launch completion changed')
  after=os.stat(self.NAME,dir_fd=self.fd,follow_symlinks=False)
  if (after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size,before.st_mtime_ns,before.st_ctime_ns):raise RuntimeError('intent changed before archive')
  dest='receiver-launch-complete-'+self.run+'.json'
  try:os.stat(dest,dir_fd=self.fd,follow_symlinks=False)
  except FileNotFoundError:pass
  else:raise RuntimeError('completed intent exists')
  os.rename(self.NAME,dest,src_dir_fd=self.fd,dst_dir_fd=self.fd);os.fsync(self.fd);return True
 def archive_recovered(self,result,*,independent_proof):
  if self.fd is None or not self.used or not hasattr(self,'file_identity') or type(result) is not dict or result.get('run')!=self.run or result.get('status')!='recovered' or result.get('modeZeroVerified') is not True or result.get('oldReceiverExitVerified') is not True or result.get('journalArchived') is not True or not callable(independent_proof) or independent_proof() is not True:raise RuntimeError('launch completion unverified')
  before=os.stat(self.NAME,dir_fd=self.fd,follow_symlinks=False)
  if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o640 or (before.st_dev,before.st_ino,before.st_uid,before.st_gid)!=self.file_identity or before.st_size>4096:raise RuntimeError('intent changed')
  f=os.open(self.NAME,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self.fd)
  try:
   info=os.fstat(f);raw=os.read(f,4097)
   if (info.st_dev,info.st_ino,info.st_uid,info.st_gid)!=self.file_identity or len(raw)!=before.st_size or json.loads(raw)!=self.event:raise RuntimeError('intent contents changed')
  finally:os.close(f)
  if independent_proof() is not True:raise RuntimeError('launch completion changed')
  after=os.stat(self.NAME,dir_fd=self.fd,follow_symlinks=False)
  if (after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size,before.st_mtime_ns,before.st_ctime_ns):raise RuntimeError('intent changed before archive')
  dest='receiver-launch-recovered-'+self.run+'.json'
  try:os.stat(dest,dir_fd=self.fd,follow_symlinks=False)
  except FileNotFoundError:pass
  else:raise RuntimeError('completed intent exists')
  os.rename(self.NAME,dest,src_dir_fd=self.fd,dst_dir_fd=self.fd);os.fsync(self.fd);return True
 def close(self):
  if self.fd is not None:os.close(self.fd);self.fd=None
