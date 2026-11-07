"""Exact paired-target and read-only HID opening for a later receiver app.

Uses existing bounded inventory and identity checks. No calls are made on
import. This does not initiate a connection or send an input/sensor command.
"""
from runtime_device import registered_name_matches
import math,os,stat,subprocess,time
import tv_bluetooth
from hid_input import scan_devices,identity
from hid_orphan import unregistered
from hid_nodes import valid_index

def paired_target(invoke=subprocess.Popen):
 reply=tv_bluetooth._call('device/getStatus',{'subscribe':False},invoke)
 if type(reply) is not dict or reply.get('returnValue') is not True or type(reply.get('devices')) is not list:return False
 found=[item for item in reply['devices'] if type(item) is dict and str(item.get('address','')).lower()==tv_bluetooth.TARGET and registered_name_matches(item,tv_bluetooth.NAME)]
 return len(found)==1 and found[0].get('paired') is True and found[0].get('blocked') is False and found[0].get('pairing') is False

class RecoveryPairingCheck:
 """Reuse a status read for at most 250 ms within one connected recovery.

 The live connection/lease guard is still checked on every call. Any failure
 permanently invalidates this instance; it cannot cross a reconnect. The
 final recovery confirmation requests a fresh status read explicitly.
 """
 def __init__(self,check,control,*,clock=time.monotonic):
  if not all(callable(x) for x in (check,control,clock)):raise ValueError('invalid pairing check')
  self.check=check;self.control=control;self.clock=clock
  self.observed=None;self.previous=None;self.failed=False
 def __call__(self,*,fresh=False):
  if self.failed:return False
  try:
   now=self.clock()
   if (type(now) not in (int,float) or not math.isfinite(now)
       or (self.previous is not None and now<self.previous)
       or self.control() is not True):raise RuntimeError('pairing control changed')
   self.previous=now
   if fresh or self.observed is None or now-self.observed>=.25:
    if self.check() is not True or self.control() is not True:raise RuntimeError('pairing unconfirmed')
    after=self.clock()
    if type(after) not in (int,float) or not math.isfinite(after) or after<now:raise RuntimeError('pairing clock changed')
    self.previous=after;self.observed=now
   return True
  except Exception:
   self.failed=True;return False

def transient_disappeared(inv):
 if type(inv) is not dict or inv.get('inventoryComplete') is not False or inv.get('allOpenedFdsClosed') is not True:return False
 nodes=inv.get('nodes');buckets=inv.get('errnoBuckets')
 if type(nodes) is not list or not nodes or type(buckets) is not dict or any(k!='ENOENT' or type(v) is not int or v<0 for k,v in buckets.items()):return False
 if not any(type(n) is dict and n.get('inspectionErrno')=='ENODEV' for n in nodes):return False
 for n in nodes:
  if type(n) is not dict:return False
  if n.get('inspectionErrno')=='ENODEV':
   if n.get('openedReadOnly') is not False or n.get('identityChecked') is not False or n.get('inspectionError') is not None or n.get('closeErrno') is not None:return False
  elif n.get('openedReadOnly') is not True or n.get('identityChecked') is not True or n.get('fdClosed') is not True or n.get('inspectionErrno') is not None or n.get('inspectionError') is not None or n.get('closeErrno') is not None:return False
 return True

def _open_target_once(*,inventory=scan_devices,lstat=os.lstat,open_fn=os.open,fstat=os.fstat,identity_fn=identity,close_fn=os.close,allow_retry=None,wait=time.sleep,orphan_check=unregistered):
 if allow_retry is not None and not callable(allow_retry):raise ValueError('invalid retry guard')
 inv=inventory(timeout=10);orphans=[]
 # Retry only when every incomplete node disappeared before open and all
 # opened descriptors were closed. Never suppress unrelated scan failures.
 if transient_disappeared(inv) and allow_retry is not None and allow_retry() is True:
  first=inv
  def missing(v):
   return sorted((n.get('index'),n.get('rdevMajor'),n.get('rdevMinor')) for n in v['nodes'] if n.get('inspectionErrno')=='ENODEV')
  a=missing(first)
  # Known unregistered character nodes need no settling delay. Still repeat
  # the complete inventory and prove their absence again before and after
  # opening the exact remote. An unknown or registering node keeps the delay.
  ids=first.get('targetCandidateIndexes')
  fast=(type(ids) is list and len(ids)==1 and valid_index(ids[0])
        and all(type(x) is int for row in a for x in row)
        and all(orphan_check(index=i,major=ma,minor=mi) is True for i,ma,mi in a))
  if not fast:wait(.2)
  if allow_retry() is True:
   inv=inventory(timeout=10)
   if transient_disappeared(inv) and allow_retry() is True:
    b=missing(inv)
    if a==b and all(type(x) is int for row in b for x in row) and all(orphan_check(index=i,major=ma,minor=mi) is True for i,ma,mi in b):
     # These nodes have no registered kernel device; they cannot hide another
     # usable target at the instant checked. Preserve all other strict checks.
     orphans=b;inv={**inv,'inventoryComplete':True}
 if type(inv) is not dict or inv.get('inventoryComplete') is not True or inv.get('allOpenedFdsClosed') is not True:raise RuntimeError('target inventory incomplete')
 ids=inv.get('targetCandidateIndexes')
 if type(ids) is not list:raise RuntimeError('target inventory invalid')
 if len(ids)==0:raise RuntimeError('target not present')
 if len(ids)!=1:raise RuntimeError('target ambiguous')
 if not valid_index(ids[0]):raise RuntimeError('target inventory invalid')
 path='/dev/hidraw'+str(ids[0]);before=lstat(path)
 if not stat.S_ISCHR(before.st_mode) or stat.S_ISLNK(before.st_mode):raise RuntimeError('target node invalid')
 fd=open_fn(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  opened=fstat(fd);after=lstat(path)
  if not stat.S_ISCHR(opened.st_mode) or not stat.S_ISCHR(after.st_mode) or (before.st_ino,before.st_dev,before.st_rdev)!=(opened.st_ino,opened.st_dev,opened.st_rdev) or (opened.st_ino,opened.st_dev,opened.st_rdev)!=(after.st_ino,after.st_dev,after.st_rdev):raise RuntimeError('target node changed')
  ident=identity_fn(fd)
  if type(ident) is not dict or ident.get('matches') is not True:raise RuntimeError('target identity mismatch')
  if orphans and (allow_retry() is not True or any(orphan_check(index=i,major=ma,minor=mi) is not True for i,ma,mi in orphans)):raise RuntimeError('orphan proof changed')
  from touch_surface import bind_product
  bind_product(ident.get('product'))
  return fd
 except BaseException:
  close_fn(fd);raise

def open_target(*,inventory=scan_devices,allow_retry=None,wait=time.sleep,clock=time.monotonic,wait_for_target=True,**kwargs):
 """Allow asynchronous HID registration after an acknowledged input start.

 Re-scan only a complete inventory with no matching device. Every attempt
 retains the full identity checks; incomplete or ambiguous scans fail at once.
 This does not resend input-start or keep a descriptor from a failed attempt.
 """
 if allow_retry is not None and not callable(allow_retry):raise ValueError('invalid retry guard')
 if type(wait_for_target) is not bool:raise ValueError('invalid target wait policy')
 deadline=None;previous=None
 def scan(*,timeout):
  if deadline is not None:timeout=min(timeout,max(.01,deadline-clock()))
  return inventory(timeout=timeout)
 for attempt in range(41):
  try:
   return _open_target_once(inventory=scan,allow_retry=allow_retry,wait=wait,**kwargs)
  except RuntimeError as exc:
   if str(exc)!='target not present' or not wait_for_target or allow_retry is None or attempt==40:raise
   now=clock()
   if (type(now) not in (int,float) or not math.isfinite(now)
       or (previous is not None and now<previous) or allow_retry() is not True):raise
   if deadline is None:deadline=now+2
   if now>=deadline:raise
   previous=now;wait(min(.05,deadline-now));after=clock()
   if (type(after) not in (int,float) or not math.isfinite(after)
       or after<previous or after>=deadline or allow_retry() is not True):raise
   previous=after
