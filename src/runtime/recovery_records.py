"""Distinct durable recovery records; preserves prior uncertain journal bytes."""
import json,os,stat,re
from pathlib import Path
from borrowed_runtime_journal import inspect_journal

class RecoveryRecords:
 def __init__(self,directory,run,*,state_uid=5999,group=5000):
  self.run=run;self.sequence=0;self.fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
  s=os.fstat(self.fd)
  if s.st_uid!=state_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in (0o770,0o775):
   self.close();raise RuntimeError('unsafe recovery state')
 def __call__(self,event):
  # O_EXCL first record is the cross-restart no-retry latch.
  self.sequence+=1;name='recovery-'+self.run+'-'+str(self.sequence)+'.json'
  f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=self.fd)
  with os.fdopen(f,'wb') as stream:
   os.fchmod(stream.fileno(),0o640);stream.write((json.dumps({'run':self.run,**event},sort_keys=True)+'\n').encode());stream.flush();os.fsync(stream.fileno())
  os.fsync(self.fd);return True
 def close(self):
  if self.fd is not None:os.close(self.fd);self.fd=None

def archive_uncertain(directory,run,*,owner_uid,proof,state_uid=5999,group=5000):
 if proof() is not True:raise RuntimeError('recovery proof missing')
 d=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe recovery parent')
  before=os.stat('borrowed-active',dir_fd=d,follow_symlinks=False)
  if not stat.S_ISDIR(before.st_mode) or before.st_uid!=owner_uid or before.st_gid!=group or stat.S_IMODE(before.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe uncertain session')
  activefd=os.open('borrowed-active',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  try:
   names=os.listdir(activefd)
   if not names or any(not re.fullmatch('borrowed-'+run+r'-[0-9]{2,4}\.json',name) for name in names):raise RuntimeError('foreign or empty recovery journal')
  finally:os.close(activefd)
  evidence=inspect_journal(Path(directory)/'borrowed-active',run,owner_uid=owner_uid,state_uid=owner_uid,group=group,historical=True)
  if evidence.get('status') not in ('sensor-state-unknown','zero-recorded-live-recheck-required','no-sensor-enable-recorded','input-start-recorded-sensor-not-attempted'):raise RuntimeError('uncertain sensor journal not established')
  dest='borrowed-recovered-'+run
  try:os.stat(dest,dir_fd=d,follow_symlinks=False)
  except FileNotFoundError:pass
  else:raise RuntimeError('recovered archive exists')
  after=os.stat('borrowed-active',dir_fd=d,follow_symlinks=False)
  if before!=after or proof() is not True:raise RuntimeError('recovery journal changed')
  os.rename('borrowed-active',dest,src_dir_fd=d,dst_dir_fd=d);os.fsync(d);return True
 finally:os.close(d)
