"""Continuously wait for a previously bonded remote without sending a connect.

Candidate only: no device calls occur on import. A 106 or missing response is
unknown, never evidence of a connected or disconnected GATT link. Device and
both profiles must be freshly confirmed before the supervisor may start.
"""
from runtime_device import registered_name_matches
import math,time
from borrowed_gatt_view import TARGET
from connected_status_watch import ConnectedStatusWatch
from resident_autoconnect import NAME

class ClockError(RuntimeError):pass

def wait_connected(*,client,lease,stop,clock=time.monotonic,wait=None,interval=5,max_profile_age=2,max_inventory_age=8,require_disconnect=False,emit=lambda _:None):
 if not callable(client) or not callable(clock) or not callable(emit) or not callable(getattr(lease,'held',None)) or not callable(getattr(stop,'is_set',None)) or not callable(getattr(stop,'wait',None)) or type(interval) not in (int,float) or not 1<=interval<=60 or type(max_profile_age) not in (int,float) or not 0<max_profile_age<=5 or type(max_inventory_age) not in (int,float) or not 0<max_inventory_age<=10 or type(require_disconnect) is not bool:raise ValueError('invalid dependencies')
 wait=stop.wait if wait is None else wait
 if not callable(wait):raise ValueError('invalid wait')
 previous=None;last=None;disconnected=not require_disconnect
 def now():
  nonlocal last
  try:value=clock()
  except Exception as exc:raise ClockError('clock unavailable') from exc
  if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (last is not None and value<last):raise ClockError('invalid clock')
  last=value;return value
 def state(value):
  nonlocal previous
  if value!=previous:emit(value);previous=value
 while not stop.is_set():
  if lease.held() is not True:return {'status':'lease-lost'}
  try:
   now();d=client('device/getStatus',{'subscribe':False},timeout=4);inventory_time=now()
   rows=d.get('devices') if type(d) is dict and d.get('returnValue') is True else None
   targets=[r for r in rows if type(r) is dict and str(r.get('address','')).lower()==TARGET] if type(rows) is list else []
   if len(targets)!=1 or not registered_name_matches(targets[0],NAME) or targets[0].get('paired') is not True or targets[0].get('blocked') is not False or targets[0].get('pairing') is not False:
    state('target-unconfirmed')
   else:
    hid=client('hid/getStatus',{'address':TARGET},timeout=1);hid_time=now()
    gatt=client('gatt/getStatus',{'address':TARGET},timeout=1);after=now()
    fresh=(lease.held() is True and not stop.is_set() and after-hid_time<=max_profile_age and after-inventory_time<=max_inventory_age and ConnectedStatusWatch.valid(hid) and ConnectedStatusWatch.valid(gatt))
    if fresh and all(all(p[k] is False for k in ('connected','connecting','connectRequest')) for p in (hid,gatt)):
     disconnected=True
    if fresh and disconnected and ConnectedStatusWatch.connected(hid) and ConnectedStatusWatch.connected(gatt):
     state('connected');return {'status':'connected','disconnectObserved':True} if require_disconnect else {'status':'connected'}
    state('waiting')
  except ClockError:
   return {'status':'invalid-clock'}
  except Exception:
   state('unavailable')
  if not stop.is_set():wait(interval)
 return {'status':'stopped'}
