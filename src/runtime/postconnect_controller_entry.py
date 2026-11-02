"""Experimental TV-local post-connect controller entry; no boot registration.

Not installed or device-validated. Its receiver config is provisioned only by
an explicitly scoped installer and must pin the separately built B package.
"""
import json,os,signal,stat,threading,time
from pathlib import Path
from autonomous_gyro_b import ordinary
from persistent_status_pump import PersistentConnectedStatusPump
from supervisor_lease import SupervisorLease
from postconnect_supervisor_cycle import SupervisorCycle
from postconnect_supervisor_loop import run_loop
from receiver_result_receipt import _process_identity

APP='org.codex.siriremote.autocoord20261029v'
B='org.codex.siriremote.hidgattrouterb20261029u'
ROOT=Path('/media/developer/apps/usr/palm/applications')
PKG=Path('/media/developer/apps/usr/palm/packages')
STATE=ROOT/APP/'state'
EXPECTED_PROVISIONER_UID=5415  # observed developer UID on this TV; revalidate after firmware/account changes

def load_config(state=STATE):
 d=os.open(Path(state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  s=os.fstat(d)
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=5999 or s.st_gid!=5000 or stat.S_IMODE(s.st_mode)!=0o770:raise RuntimeError('controller state invalid')
  f=os.open('receiver-pin.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  try:
   x=os.fstat(f)
   if not stat.S_ISREG(x.st_mode) or x.st_nlink!=1 or x.st_uid!=EXPECTED_PROVISIONER_UID or x.st_gid!=5000 or stat.S_IMODE(x.st_mode)!=0o640 or x.st_size>32768:raise RuntimeError('receiver pin invalid')
   raw=os.read(f,32769)
   if len(raw)!=x.st_size:raise RuntimeError('receiver pin read incomplete')
   end=os.fstat(f)
   if (end.st_dev,end.st_ino,end.st_uid,end.st_gid,end.st_size,end.st_mtime_ns,end.st_ctime_ns)!=(x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_size,x.st_mtime_ns,x.st_ctime_ns):raise RuntimeError('receiver pin changed')
  finally:os.close(f)
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate pin key')
    out[k]=v
   return out
  pin=json.loads(raw,object_pairs_hook=unique)
  if type(pin) is not dict or set(pin)!={'appId','files','packageInfoSha256'} or pin['appId']!=B:raise RuntimeError('receiver pin shape invalid')
  return pin
 finally:os.close(d)

def main():
 ordinary();pin=load_config();stop=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda _s,_f:stop.set())
 lease=SupervisorLease(STATE);pump=None;timer=None
 try:
  process=_process_identity()
  # The flock is released on process exit. The durable launch intent is the
  # cross-restart latch and must be clear before starting a new watcher.
  try:os.stat('receiver-launch-intent.json',dir_fd=lease.dirfd,follow_symlinks=False)
  except FileNotFoundError:pass
  else:return 2
  pump=PersistentConnectedStatusPump()
  pump.start()
  # Finite test variant: stop after the first completed cycle or deadline.
  timer=threading.Timer(300,stop.set);timer.daemon=True;timer.start()
  def cycle():
   import secrets
   return SupervisorCycle(watch=pump.tracker,lease=lease,controller_state=STATE,receiver_state=ROOT/B/'state',run=secrets.token_hex(16),controller_process=process,receiver_app=str(ROOT/B),receiver_package=str(PKG/B),receiver_pin=pin,allow_exe_permission_denied=True)
  def emit(event):
   if event=='session-complete':stop.set()
   elif event=='waiting-for-connection':
    name='controller-ready-'+str(os.getpid())+'-'+str(process['startTicks'])+'.json'
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=lease.dirfd)
    try:
     os.fchmod(fd,0o640)
     with os.fdopen(fd,'wb') as stream:
      fd=None;stream.write((json.dumps({'schema':1,'appId':APP,'stage':'waiting-for-connection','pid':os.getpid(),'startTicks':process['startTicks'],'epochMs':int(time.time()*1000)},separators=(',',':'))+'\n').encode());stream.flush();os.fsync(stream.fileno())
     os.fsync(lease.dirfd)
    finally:
     if fd is not None:os.close(fd)
  result=run_loop(watch=pump.tracker,lease=lease,cycle_factory=cycle,stop=stop,emit=emit)
  return 0 if result.get('status')=='stopped' else 2
 finally:
  try:
   if timer is not None:timer.cancel()
   if pump is not None and pump.stop() is not True:raise RuntimeError('status pump stop unverified')
  finally:lease.close()

if __name__=='__main__':raise SystemExit(main())
