"""Bounded, fail-closed recovery of an interrupted HID connect intent.

This module performs no work until explicitly called by the lease owner.
"""
from runtime_device import connect_intent
import math,os,stat,time,uuid
from pathlib import Path
from connected_status_watch import ConnectedStatusWatch
from resident_autoconnect import NAME
from borrowed_gatt_view import TARGET

INTENT='bootstrap-connect-intent.json'
EXPECTED=connect_intent()

def no_connect_process(proc='/proc'):
 count=0
 with os.scandir(proc) as entries:
  for e in entries:
   if not e.name.isdecimal():continue
   count+=1
   if count>4096:raise RuntimeError('process scan incomplete')
   try:
    with open(Path(proc)/e.name/'cmdline','rb') as f:raw=f.read(8193)
   except FileNotFoundError:continue
   except OSError as exc:raise RuntimeError('process scan incomplete') from exc
   if len(raw)>8192:raise RuntimeError('process command too long')
   args=raw.split(b'\0')
   if args and args[0]==b'/usr/bin/luna-send-pub' and any(x.endswith(b'/hid/connect') for x in args[1:]) and any(TARGET.encode() in x.lower() for x in args[1:]):return False
 return True

def retire_idle(lease,*,group=5000):
 if lease.held() is not True:raise RuntimeError('lease unavailable')
 fd=os.open(INTENT,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=lease.dirfd)
 try:
  s=os.fstat(fd)
  if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_gid!=group or stat.S_IMODE(s.st_mode)!=0o640 or s.st_size!=len(EXPECTED) or os.read(fd,len(EXPECTED)+1)!=EXPECTED:raise RuntimeError('intent mismatch')
  p=os.stat(INTENT,dir_fd=lease.dirfd,follow_symlinks=False)
  if (s.st_dev,s.st_ino)!=(p.st_dev,p.st_ino) or lease.held() is not True:raise RuntimeError('intent changed')
  archive='bootstrap-connect-idle-'+uuid.uuid4().hex+'.json'
  os.link(INTENT,archive,src_dir_fd=lease.dirfd,dst_dir_fd=lease.dirfd,follow_symlinks=False)
  old=os.stat(INTENT,dir_fd=lease.dirfd,follow_symlinks=False);new=os.stat(archive,dir_fd=lease.dirfd,follow_symlinks=False)
  if (old.st_dev,old.st_ino)!=(s.st_dev,s.st_ino) or (new.st_dev,new.st_ino)!=(s.st_dev,s.st_ino) or lease.held() is not True:raise RuntimeError('archive changed')
  os.fsync(lease.dirfd);os.unlink(INTENT,dir_fd=lease.dirfd);os.fsync(lease.dirfd)
  return True
 finally:os.close(fd)

def recover_idle(*,lease,stop,client,deadline,clock=time.monotonic,wait=None,scan=no_connect_process,retire=retire_idle,window=40,emit=lambda _event:None):
 if type(window) not in (int,float) or not 40<=window<=60 or not callable(client) or not callable(scan) or not callable(clock) or not callable(emit):raise ValueError('invalid recovery config')
 wait=stop.wait if wait is None else wait
 def mark(event):
  try:emit(event)
  except Exception:pass
 def guard():return lease.held() is True and not stop.is_set()
 def now():
  v=clock()
  if type(v) not in (int,float) or not math.isfinite(v) or v<0:raise RuntimeError('invalid clock')
  return v
 def inventory():
  d=client('device/getStatus',{'subscribe':False},timeout=4)
  rows=d.get('devices') if type(d) is dict and d.get('returnValue') is True else None
  rows=[r for r in rows if type(r) is dict and str(r.get('address','')).lower()==TARGET] if type(rows) is list else []
  return len(rows)==1 and rows[0].get('name')==NAME and rows[0].get('paired') is True and rows[0].get('blocked') is False and rows[0].get('pairing') is False
 def idle():
  p=client('hid/getStatus',{'address':TARGET},timeout=1)
  return ConnectedStatusWatch.valid(p) and all(p.get(k) is False for k in ('connected','connecting','connectRequest'))
 try:
  mark('idle-recovery-start');begin=now();last=begin
  if not guard():mark('idle-guard-unavailable');return False
  if deadline-begin<window:mark('idle-deadline-too-short');return False
  if not inventory():mark('idle-inventory-unavailable');return False
  if not scan():mark('idle-connect-process-present');return False
  mark('idle-observation-start')
  while guard():
   a=now()
   if a<last or a>deadline:mark('idle-clock-or-deadline');return False
   last=a
   if not idle():mark('idle-profile-not-idle');return False
   if not guard():mark('idle-guard-unavailable');return False
   after=now()
   if after<a or after-a>2 or after>deadline:mark('idle-profile-stale');return False
   if after-begin>=window:
    if not inventory():mark('idle-final-inventory-unavailable');return False
    if not scan():mark('idle-final-connect-process-present');return False
    if not guard():mark('idle-guard-unavailable');return False
    if not idle():mark('idle-final-profile-not-idle');return False
    if not guard() or now()>deadline:mark('idle-final-guard-or-deadline');return False
    mark('idle-retire-attempt');done=retire(lease) is True
    mark('idle-retired' if done else 'idle-retire-unconfirmed');return done
   wait(min(5,max(0,window-(after-begin))))
  mark('idle-guard-unavailable');return False
 except (OSError,RuntimeError,ValueError,AttributeError,TypeError) as exc:
  mark('idle-error-'+type(exc).__name__);return False
