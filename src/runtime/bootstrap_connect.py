"""Connection bootstrap with no import-time I/O.

GATT 106 is unknown, never a connected/disconnected proof. An uncertain
durable intent remains until both target profiles are independently
confirmed.
"""
from runtime_device import registered_name_matches
from runtime_device import connect_intent
import math,os,stat,time,uuid
from connected_status_watch import ConnectedStatusWatch
from resident_autoconnect import ConnectClient,NAME
from borrowed_gatt_view import TARGET
from idle_recovery import recover_idle
from pumping_luna_client import LunaCallError

def inventory_result(value):
 """Return a bounded reason, without recording device names or addresses."""
 if type(value) is not dict:return 'invalid-response'
 if value.get('returnValue') is False:
  code=value.get('errorCode')
  if type(code) is int and 0<=code<=9999:return 'service-error-'+str(code)
  return 'service-error'
 if value.get('returnValue') is not True:return 'invalid-success-flag'
 if type(value.get('devices')) is not list:return 'missing-devices'
 return 'ok'

class BootstrapClient(ConnectClient):
 def _validate_request(self,method,params,timeout):
  if method in ('hid/getStatus','gatt/getStatus') and params=={'address':TARGET} and type(params) is dict and timeout==1:
   return method,1,False
  return super()._validate_request(method,params,timeout)

def reserve_intent(lease):
 fd=os.open('bootstrap-connect-intent.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=lease.dirfd)
 try:
  os.fchmod(fd,0o640)
  payload=connect_intent()
  if os.write(fd,payload)!=len(payload):raise OSError('intent write incomplete')
  os.fsync(fd)
 finally:os.close(fd)
 os.fsync(lease.dirfd)

def retire_confirmed_intent(lease,*,group=5000):
 """Archive only our exact durable intent after independent connection proof.

 Caller must hold the lease and have just verified both profiles connected,
 idle and addressed to the bonded target. Missing intent is a harmless no-op.
 A malformed or replaced file is retained and raises.
 """
 if lease.held() is not True:raise RuntimeError('lease unavailable')
 name='bootstrap-connect-intent.json'
 try:fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=lease.dirfd)
 except FileNotFoundError:return False
 try:
  s=os.fstat(fd);expected=connect_intent()
  if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in (0o640,0o775) or s.st_size!=len(expected):raise RuntimeError('unsafe bootstrap intent')
  if os.read(fd,len(expected)+1)!=expected:raise RuntimeError('bootstrap intent content changed')
  current=os.stat(name,dir_fd=lease.dirfd,follow_symlinks=False)
  if (s.st_dev,s.st_ino)!=(current.st_dev,current.st_ino) or lease.held() is not True:raise RuntimeError('bootstrap intent replaced')
  archive='bootstrap-connect-confirmed-'+uuid.uuid4().hex+'.json'
  os.link(name,archive,src_dir_fd=lease.dirfd,dst_dir_fd=lease.dirfd,follow_symlinks=False)
  saved=os.stat(archive,dir_fd=lease.dirfd,follow_symlinks=False);current=os.stat(name,dir_fd=lease.dirfd,follow_symlinks=False)
  if (s.st_dev,s.st_ino)!=(saved.st_dev,saved.st_ino) or (s.st_dev,s.st_ino)!=(current.st_dev,current.st_ino) or lease.held() is not True:raise RuntimeError('bootstrap intent changed during archive')
  os.fsync(lease.dirfd);os.unlink(name,dir_fd=lease.dirfd);os.fsync(lease.dirfd)
  return True
 finally:os.close(fd)

def confirm_and_retire(*,client,lease,stop,clock=time.monotonic,retire=retire_confirmed_intent):
 """Conservatively resolve a prior intent after passive reconnection."""
 try:
  start=clock()
  if lease.held() is not True or stop.is_set():return False
  hid=client('hid/getStatus',{'address':TARGET},timeout=1)
  gatt=client('gatt/getStatus',{'address':TARGET},timeout=1)
  end=clock()
  if type(start) not in (int,float) or type(end) not in (int,float) or not math.isfinite(start) or not math.isfinite(end) or not 0<=end-start<=3 or lease.held() is not True or stop.is_set():return False
  if not all(ConnectedStatusWatch.valid(p) and ConnectedStatusWatch.connected(p) for p in (hid,gatt)):return False
  retire(lease);return True
 except (OSError,RuntimeError,ValueError,AttributeError):return False

def bootstrap(*,lease,stop,deadline,clock=time.monotonic,client_factory=BootstrapClient,reserve=reserve_intent,retire=retire_confirmed_intent,recover=recover_idle,wait=None,trace=lambda _event:None,wait_for_ready=False):
 """Return proof only after real HID+GATT status; otherwise fail closed.

No retry on rejection, timeout, spawn failure, or process restart while the
intent remains unresolved. The caller starts the status pump after success.
With wait_for_ready, read-only preflight waits until stop/lease loss; the
original remaining connection budget starts only once preflight succeeds.
"""
 if type(deadline) not in (int,float) or not math.isfinite(deadline) or not callable(trace) or type(wait_for_ready) is not bool:raise ValueError('invalid bootstrap configuration')
 budget=max(0,deadline-clock());preparing=True
 if budget<=0:return False
 def mark(event):
  try:trace(event)
  except Exception:pass
 wait=stop.wait if wait is None else wait
 def guard():return not stop.is_set() and lease.held() is True and ((wait_for_ready and preparing) or clock()<deadline)
 def read(role):return status_client(role+'/getStatus',{'address':TARGET},timeout=1)
 def idle(p):return ConnectedStatusWatch.valid(p) and all(p[k] is False for k in ('connected','connecting','connectRequest'))
 def connected(p):return ConnectedStatusWatch.valid(p) and ConnectedStatusWatch.connected(p)
 def resolved():
  # Failure to archive preserves the conservative one-shot latch. It does not
  # invalidate an independently observed already-connected target.
  try:retire(lease)
  except (OSError,RuntimeError,AttributeError):pass
  return True
 def unknown(p):return type(p) is dict and p.get('returnValue') is False and type(p.get('errorCode')) is int and p['errorCode']==106
 def dispatch_ready():
  # Fresh HID read immediately before Popen; GATT is not used as idle proof.
  started=clock();p=read('hid')
  return guard() and 0<=clock()-started<=2 and idle(p)
 def preflight():
  d=status_client('device/getStatus',{'subscribe':False},timeout=4)
  if not guard():return 'bootstrap-guard-unavailable'
  result=inventory_result(d)
  if result!='ok':return 'bootstrap-inventory-'+result
  matches=[x for x in d['devices'] if type(x) is dict and str(x.get('address','')).lower()==TARGET]
  if len(matches)!=1:return 'bootstrap-target-not-unique'
  target=matches[0]
  if not registered_name_matches(target,NAME) or target.get('paired') is not True or target.get('blocked') is not False or target.get('pairing') is not False:return 'bootstrap-target-ineligible'
  hid=read('hid');gatt=read('gatt')
  if not guard():return 'bootstrap-guard-unavailable'
  if connected(hid) and connected(gatt):return 'connected'
  if not idle(hid):return 'bootstrap-hid-not-idle'
  if not (ConnectedStatusWatch.valid(gatt) or unknown(gatt)):return 'bootstrap-gatt-invalid'
  return 'ready'
 status_client=client_factory(pump=lambda:None,guard=guard,clock=clock,native_app=True)
 client=client_factory(pump=lambda:None,guard=guard,clock=clock,native_app=True,pre_dispatch=dispatch_ready)
 try:
  mark('bootstrap-start')
  if not guard():mark('bootstrap-guard-unavailable');return False
  previous=None
  while guard():
   # No intent is reserved and no connection request can be dispatched here.
   # Every retry rechecks the exact bonded target, not just service availability.
   try:reason=preflight()
   except LunaCallError:reason='bootstrap-call-error'
   except (OSError,RuntimeError,ValueError,TypeError,AttributeError) as exc:reason='bootstrap-error-'+type(exc).__name__
   if not guard():mark('bootstrap-guard-unavailable');return False
   if reason=='connected':mark('bootstrap-already-connected');return resolved()
   if reason=='ready':break
   if reason!=previous:mark(reason);previous=reason
   if not wait_for_ready:return False
   wait(5)
  else:mark('bootstrap-guard-unavailable');return False
  preparing=False
  if wait_for_ready:deadline=clock()+budget
  # A prior ambiguous request is never resent until a bounded series of
  # exact-target idle observations and a complete process scan permit archival.
  try:reserve(lease);mark('bootstrap-reserved')
  except FileExistsError:
   mark('bootstrap-prior-intent')
   if not recover(lease=lease,stop=stop,client=status_client,deadline=deadline,clock=clock,wait=wait,emit=mark):mark('bootstrap-recovery-not-complete');return False
   mark('bootstrap-recovery-complete')
   if not guard():return False
   reserve(lease)
  if not guard() or not dispatch_ready():return False
  mark('bootstrap-connect-attempt')
  try:client('hid/connect',{'address':TARGET},timeout=35)
  except Exception:pass  # Possibly accepted: observe only, never resend.
  while guard():
   hid=read('hid');gatt=read('gatt')
   if not guard():return False
   if connected(hid) and connected(gatt):return resolved()
   if not ConnectedStatusWatch.valid(hid) or not (ConnectedStatusWatch.valid(gatt) or unknown(gatt)):return False
   wait(min(.5,max(0,deadline-clock())))
 except LunaCallError:mark('bootstrap-call-error');return False
 except Exception as exc:mark('bootstrap-error-'+type(exc).__name__);return False
 mark('bootstrap-finished-without-connection');return False
