"""Exact paired-target and read-only HID opening for a later receiver app.

Uses existing bounded inventory and identity checks. No calls are made on
import. This does not initiate a connection or send an input/sensor command.
"""
from runtime_device import registered_name_matches
import os,stat,subprocess,time
import tv_bluetooth
from hid_input import scan_devices,identity
from hid_orphan import unregistered

def paired_target(invoke=subprocess.Popen):
 reply=tv_bluetooth._call('device/getStatus',{'subscribe':False},invoke)
 if type(reply) is not dict or reply.get('returnValue') is not True or type(reply.get('devices')) is not list:return False
 found=[item for item in reply['devices'] if type(item) is dict and str(item.get('address','')).lower()==tv_bluetooth.TARGET and registered_name_matches(item,tv_bluetooth.NAME)]
 return len(found)==1 and found[0].get('paired') is True and found[0].get('blocked') is False and found[0].get('pairing') is False

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

def open_target(*,inventory=scan_devices,lstat=os.lstat,open_fn=os.open,fstat=os.fstat,identity_fn=identity,close_fn=os.close,allow_retry=None,wait=time.sleep,orphan_check=unregistered):
 if allow_retry is not None and not callable(allow_retry):raise ValueError('invalid retry guard')
 inv=inventory(timeout=10);orphans=[]
 # Retry only when every incomplete node disappeared before open and all
 # opened descriptors were closed. Never suppress unrelated scan failures.
 if transient_disappeared(inv) and allow_retry is not None and allow_retry() is True:
  first=inv
  wait(.2)
  if allow_retry() is True:
   inv=inventory(timeout=10)
   if transient_disappeared(inv) and allow_retry() is True:
    def missing(v):
     return sorted((n.get('index'),n.get('rdevMajor'),n.get('rdevMinor')) for n in v['nodes'] if n.get('inspectionErrno')=='ENODEV')
    a=missing(first);b=missing(inv)
    if a==b and all(type(x) is int for row in b for x in row) and all(orphan_check(index=i,major=ma,minor=mi) is True for i,ma,mi in b):
     # These nodes have no registered kernel device; they cannot hide another
     # usable target at the instant checked. Preserve all other strict checks.
     orphans=b;inv={**inv,'inventoryComplete':True}
 if type(inv) is not dict or inv.get('inventoryComplete') is not True or inv.get('allOpenedFdsClosed') is not True:raise RuntimeError('target inventory incomplete')
 ids=inv.get('targetCandidateIndexes')
 if type(ids) is not list:raise RuntimeError('target inventory invalid')
 if len(ids)==0:raise RuntimeError('target not present')
 if len(ids)!=1:raise RuntimeError('target ambiguous')
 if type(ids[0]) is not int or not 0<=ids[0]<32:raise RuntimeError('target inventory invalid')
 path='/dev/hidraw'+str(ids[0]);before=lstat(path)
 if not stat.S_ISCHR(before.st_mode) or stat.S_ISLNK(before.st_mode):raise RuntimeError('target node invalid')
 fd=open_fn(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  opened=fstat(fd);after=lstat(path)
  if not stat.S_ISCHR(opened.st_mode) or not stat.S_ISCHR(after.st_mode) or (before.st_ino,before.st_dev,before.st_rdev)!=(opened.st_ino,opened.st_dev,opened.st_rdev) or (opened.st_ino,opened.st_dev,opened.st_rdev)!=(after.st_ino,after.st_dev,after.st_rdev):raise RuntimeError('target node changed')
  ident=identity_fn(fd)
  if type(ident) is not dict or ident.get('matches') is not True:raise RuntimeError('target identity mismatch')
  if orphans and (allow_retry() is not True or any(orphan_check(index=i,major=ma,minor=mi) is not True for i,ma,mi in orphans)):raise RuntimeError('orphan proof changed')
  return fd
 except BaseException:
  close_fn(fd);raise
