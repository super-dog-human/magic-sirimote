"""Atomic active-to-completed directory for an receiver session.

A caller must hold the cooperative lease for the entire lifetime. An active
folder after a crash blocks a new session and is never removed
automatically. The parent directory and files are not authenticated against
hostile peers.
"""
import state_permissions
import os,re,stat
from pathlib import Path
from borrowed_runtime_journal import BorrowedRuntimeJournal,inspect_journal

class AtomicSessionDirectory:
 ACTIVE='borrowed-active'
 def __init__(self,parent,run,*,state_uid=5999,group=5000,owner_uid=None):
  if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
  self.run=run;self.group=group;self.owner=os.getuid() if owner_uid is None else owner_uid;self.dirfd=None;self.parentfd=None;self.journal=None;self.archived=False
  self.parentfd=os.open(Path(parent),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);created_identity=None
  try:
   s=os.fstat(self.parentfd)
   if not stat.S_ISDIR(s.st_mode) or s.st_uid!=state_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in state_permissions.directory_modes():raise RuntimeError('unsafe parent directory')
   self.parent_identity=(s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))
   os.mkdir(self.ACTIVE,0o770,dir_fd=self.parentfd)
   made=os.stat(self.ACTIVE,dir_fd=self.parentfd,follow_symlinks=False)
   if stat.S_ISDIR(made.st_mode) and made.st_uid==self.owner and made.st_gid==group:created_identity=(made.st_dev,made.st_ino,made.st_uid,made.st_gid)
   self.dirfd=os.open(self.ACTIVE,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self.parentfd)
   os.fchmod(self.dirfd,0o770);d=os.fstat(self.dirfd)
   if not stat.S_ISDIR(d.st_mode) or d.st_uid!=self.owner or d.st_gid!=group:raise RuntimeError('unsafe active directory')
   self.identity=(d.st_dev,d.st_ino,d.st_uid,d.st_gid)
   # Access by parent path is rechecked against the open directory identity.
   path=Path(parent)/self.ACTIVE;self.path=path
   check=os.stat(self.ACTIVE,dir_fd=self.parentfd,follow_symlinks=False)
   if (check.st_dev,check.st_ino,check.st_uid,check.st_gid)!=self.identity:raise RuntimeError('active directory changed')
   os.fsync(self.parentfd)
   self.journal=BorrowedRuntimeJournal(path,run,state_uid=self.owner,group=group)
  except BaseException:
   # A constructor failure before a journal exists may leave an empty owned
   # directory. Remove only the exact directory created here; a nonempty or
   # changed directory remains for recovery. rmdir itself enforces emptiness.
   if created_identity is not None and self.parentfd is not None:
    try:
     current=os.stat(self.ACTIVE,dir_fd=self.parentfd,follow_symlinks=False)
     if stat.S_ISDIR(current.st_mode) and (current.st_dev,current.st_ino,current.st_uid,current.st_gid)==created_identity:
      os.rmdir(self.ACTIVE,dir_fd=self.parentfd);os.fsync(self.parentfd)
    except OSError:pass
   self.close();raise
 def __call__(self,event):
  if self.archived or self.journal is None:raise RuntimeError('journal not active')
  self._check_parent()
  return self.journal(event)
 def _check_parent(self):
  s=os.fstat(self.parentfd)
  if (s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=self.parent_identity:raise RuntimeError('parent directory changed')
 def archive_completed(self,*,result,pump_stopped):
  if self.archived or self.journal is None or type(result) is not dict or result.get('status')!='complete' or result.get('sensorStopVerified') is not True or pump_stopped is not True:raise RuntimeError('successful stop not established')
  parent=os.fstat(self.parentfd);active=os.stat(self.ACTIVE,dir_fd=self.parentfd,follow_symlinks=False);opened=os.fstat(self.dirfd)
  if (parent.st_dev,parent.st_ino,parent.st_uid,parent.st_gid,stat.S_IMODE(parent.st_mode))!=self.parent_identity or (active.st_dev,active.st_ino,active.st_uid,active.st_gid)!=self.identity or (opened.st_dev,opened.st_ino,opened.st_uid,opened.st_gid)!=self.identity:raise RuntimeError('directory identity changed')
  if self.journal.stage!='sensor-zero-confirmed':raise RuntimeError('zero evidence missing')
  # Inspect saved records before atomically renaming the whole folder. The
  # live stop proof is provided by the caller; the record is historical.
  evidence=inspect_journal(self.path,self.run,owner_uid=self.owner,state_uid=self.owner,group=self.group)
  if evidence.get('status')!='zero-recorded-live-recheck-required':raise RuntimeError('journal incomplete')
  active=os.stat(self.ACTIVE,dir_fd=self.parentfd,follow_symlinks=False)
  if (active.st_dev,active.st_ino,active.st_uid,active.st_gid)!=self.identity:raise RuntimeError('active directory changed')
  name='borrowed-complete-'+self.run
  try:os.stat(name,dir_fd=self.parentfd,follow_symlinks=False)
  except FileNotFoundError:pass
  else:raise RuntimeError('completed directory already exists')
  os.fsync(self.dirfd);os.rename(self.ACTIVE,name,src_dir_fd=self.parentfd,dst_dir_fd=self.parentfd);os.fsync(self.parentfd);self.archived=True
  return True
 def discard_empty(self,*,pump_stopped):
  if self.archived or self.journal is None or pump_stopped is not True or self.journal.sequence!=0 or os.listdir(self.dirfd):raise RuntimeError('empty inactive session not established')
  self._check_parent()
  active=os.stat(self.ACTIVE,dir_fd=self.parentfd,follow_symlinks=False);opened=os.fstat(self.dirfd)
  if (active.st_dev,active.st_ino,active.st_uid,active.st_gid)!=self.identity or (opened.st_dev,opened.st_ino,opened.st_uid,opened.st_gid)!=self.identity:raise RuntimeError('directory identity changed')
  self.journal.close();self.journal=None
  os.rmdir(self.ACTIVE,dir_fd=self.parentfd);os.fsync(self.parentfd);self.archived=True
  return True
 def close(self):
  if self.journal is not None:self.journal.close();self.journal=None
  if self.dirfd is not None:os.close(self.dirfd);self.dirfd=None
  if self.parentfd is not None:os.close(self.parentfd);self.parentfd=None
