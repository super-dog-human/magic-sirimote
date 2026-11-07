"""Prepare a late pointer sink while verified navigation is already usable."""
import os,stat,threading
from output_devices import open_verified_outputs,OutputCloseError
from output_sysfs import wait_for_mouse


def verify_records(outputs,records):
 if len(records)!=2:raise RuntimeError('deferred output records incomplete')
 for fd,record in zip((outputs.key_fd,outputs.mouse_fd),records):
  opened=os.fstat(fd);path=os.lstat(record['path'])
  for value in (opened,path):
   if any(getattr(value,attr)!=record[key] for attr,key in (('st_dev','dev'),('st_ino','inode'),('st_rdev','rdev'),('st_uid','uid'),('st_gid','gid'))):
    raise RuntimeError('deferred output identity changed')
  if not stat.S_ISCHR(opened.st_mode) or opened.st_mode!=path.st_mode or oct(stat.S_IMODE(opened.st_mode))!=record['mode']:raise RuntimeError('deferred output mode changed')
 outputs._verify_mouse()


class DeferredMouse:
 def __init__(self,key_record,guard,*,scan=open_verified_outputs,verify=verify_records,thread_factory=threading.Thread):
  self.key_record=dict(key_record);self.guard=guard;self.scan=scan;self.verify=verify
  self.cancel=threading.Event();self.lock=threading.Lock();self.pending=None;self.error=None
  self.started=False;self.closed=False;self.adopted=False;self.close_error=None
  self.thread=thread_factory(target=self._prepare,name='receiver-mouse-ready')
 def live(self):return not self.cancel.is_set() and self.guard() is True
 def start(self):
  self.thread.start();self.started=True
 def _prepare(self):
  candidate=None
  try:
   while self.live():
    candidate,records,_=self.scan(allow_retry=self.live,wait=self.cancel.wait,allow_missing_mouse=True)
    if len(records) not in (1,2) or records[0]!=self.key_record:raise RuntimeError('navigation output changed during pointer preparation')
    if candidate.mouse_fd is None:
     if len(records)!=1:raise RuntimeError('deferred output records incomplete')
     # Absence is a valid startup state, not a reason to tear down navigation.
     # Each pass still validates the complete inventory and original key sink.
     # Close the unused duplicate key descriptor before waiting or rescanning.
     try:candidate.close()
     except BaseException as error:
      self.close_error=error
      raise
     finally:candidate=None
     wait_for_mouse(1.,wait=self.cancel.wait,guard=self.live)
     continue
    if len(records)!=2:raise RuntimeError('deferred output records incomplete')
    with self.lock:
     if self.live():self.pending=(candidate,records);candidate=None
    break
  except BaseException as error:
   with self.lock:
    self.error=error
    if isinstance(error,OutputCloseError):self.close_error=error
  finally:
   if candidate is not None:
    try:candidate.close()
    except BaseException as error:
     with self.lock:self.error=error;self.close_error=error
 def poll(self,owner):
  if self.closed or self.adopted:return
  with self.lock:
   if self.error is not None:raise self.error
   if self.pending is None:return
   if not self.live():raise RuntimeError('deferred output guard lost')
   # Do not move a held Enter/arrow to a different set of descriptors.
   if owner._managed_key_down():return
   candidate,records=self.pending
   self.verify(candidate,records)
   if candidate._managed_key_down():return
   if owner.mouse_fd is not None or owner.spare_key_fd is not None:raise RuntimeError('pointer already attached')
   if not self.live():raise RuntimeError('deferred output guard lost')
   # Transfer both FDs atomically under the same owner. The extra key FD is
   # retained until normal cleanup, avoiding uncertain close during adoption.
   owner.mouse_fd=candidate.mouse_fd;owner.spare_key_fd=candidate.key_fd
   candidate.mouse_fd=candidate.key_fd=None;candidate.closed=True
   self.pending=None;self.adopted=True
 def close(self):
  if self.closed:return
  self.closed=True;self.cancel.set()
  if self.started:self.thread.join()
  with self.lock:
   pending,self.pending=self.pending,None
  if pending is not None:pending[0].close()
  if self.close_error is not None:raise self.close_error
