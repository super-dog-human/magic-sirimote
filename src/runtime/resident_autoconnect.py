"""Exact bonded Siri Remote HID connection, using the TV's normal UID.

A request never establishes input ownership. The existing independent profile
pump must observe a fresh connected pair before normal receiver admission.
No discovery, pairing, disconnect, settings, sensor or input operation exists.
"""
import threading,time,subprocess
from borrowed_gatt_view import TARGET,ADAPTER
from pumping_luna_client import PumpingLunaClient,LunaCallError
from controller_connect_identity import verify_self

NAME='EXAMPLE_REMOTE_SERIAL'

class ConnectNotDispatched(LunaCallError):
 """Known stale eligibility rejected before invoking the process boundary."""

class ConnectClient(PumpingLunaClient):
 def __init__(self,*,pre_dispatch=lambda:True,**kwargs):
  spawn=kwargs.pop('spawn',subprocess.Popen)
  def checked_spawn(argv,**options):
   if len(argv)!=5 or argv[:3]!=['/usr/bin/luna-send-pub','-i','-f']:
    raise ConnectNotDispatched('unexpected transport arguments')
   if argv[3].endswith('/hid/connect') and pre_dispatch() is not True:
    raise ConnectNotDispatched('connect status changed before dispatch')
   return spawn(argv,**options)
  super().__init__(spawn=checked_spawn,**kwargs)
 def _guard(self):
  uid=self.get_euid()
  if type(uid) is not int or uid<=0 or verify_self() is not True or self.guard() is not True:
   raise LunaCallError('controller identity or lease unavailable')
 def _validate_request(self,method,params,timeout):
  if method=='device/getStatus' and type(params) is dict and params=={'subscribe':False} and timeout==4:
   return method,4,False
  if method=='hid/connect' and type(params) is dict and params=={'address':TARGET} and timeout==35:
   return method,35,True
  raise ValueError('exact paired-target connect preflight only')

class AutoConnect:
 def __init__(self,*,watch,lease,stop,clock=time.monotonic,client_factory=ConnectClient):
  self.watch=watch;self.lease=lease;self.stop=stop;self.clock=clock;self.client_factory=client_factory
  self.lock=threading.Lock();self.next_attempt=0;self.attempts=0;self.outcome='waiting';self.uncertain=False
 def guard(self):
  return self.stop.is_set() is False and self.lease.held() is True and self.watch.is_open() is True
 def tick(self):
  if not self.lock.acquire(False):return False
  try:
   now=self.clock()
   if self.watch.snapshot() is not None:
    self.connection_observed();return False
   if self.uncertain or now<self.next_attempt or not self.guard():return False
   before=self.watch.connectable_snapshot()
   if before is None:return False
   # Reserve before the first I/O; failed metadata reads cannot spin. Polling
   # generations can advance while idle, so never use generation as a retry cue.
   self.next_attempt=now+min(300,15*2**min(self.attempts,5))
   client=self.client_factory(pump=lambda:None,guard=self.guard,clock=self.clock,native_app=True,pre_dispatch=lambda:self.dispatch_ready(before))
   known=client('device/getStatus',{'subscribe':False},timeout=4)
   if known.get('returnValue') is not True or type(known.get('devices')) is not list:
    self.outcome='identity-unavailable';return False
   matches=[d for d in known['devices'] if type(d) is dict and str(d.get('address','')).lower()==TARGET]
   if len(matches)!=1:return False
   d=matches[0]
   if d.get('name')!=NAME or d.get('paired') is not True or any(k in d and d[k] is not False for k in ('pairing','blocked')) :
    self.outcome='bond-or-idle-unverified';return False
   # Recheck fresh idle profiles after metadata I/O. A transition invalidates
   # dispatch; continuing subscription/poll threads detect active requests.
   current=self.watch.connectable_snapshot()
   if current is None or current['sequence']!=before['sequence'] or not self.guard():return False
   for p in (current['hid'],current['gatt']):
    if str(p.get('address','')).lower()!=TARGET or str(p.get('adapterAddress','')).lower()!=ADAPTER or any(p.get(k) is not False for k in ('connecting','connectRequest')):return False
   if current['hid'].get('connected') is not False or type(current['gatt'].get('connected')) is not bool:return False
   self.attempts+=1;self.outcome='requesting';self.uncertain=True
   reply=client('hid/connect',{'address':TARGET},timeout=35)
   # Explicit rejection permits bounded retry. Success/timeout stays latched
   # until actual connected status; no duplicate uncertain Bluetooth request.
   if reply.get('returnValue') is False:self.uncertain=False;self.outcome='waiting-for-remote'
   else:self.outcome='awaiting-observed-connection'
   self.next_attempt=self.clock()+min(300,15*2**min(self.attempts,5))
   return True
  except ConnectNotDispatched:
   self.uncertain=False;self.outcome='status-changed-before-dispatch';return False
  except Exception:
   self.outcome='request-uncertain' if self.uncertain else 'preflight-unavailable'
   return False
  finally:self.lock.release()
 def dispatch_ready(self,before):
  value=self.watch.connectable_snapshot()
  return self.guard() and value is not None and value['sequence']==before['sequence']
 def admission_observed(self,result):
  # Called only with the actual gate launch result after begin() accepted it.
  # That result records a proven generation even if status changes immediately.
  if type(result) is not dict or result.get('status')!='accepted' or type(result.get('generation')) is not int or result['generation']<1:return False
  self.uncertain=False;self.attempts=0;self.next_attempt=self.clock()+15;self.outcome='connected';return True
 def connection_observed(self):
  if self.watch.snapshot() is not None:
   self.uncertain=False;self.attempts=0;self.next_attempt=self.clock()+15;self.outcome='connected'
