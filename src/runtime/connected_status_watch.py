"""Race-aware connected-state observation; no Bluetooth operations here.

Subscriptions provide events and the caller supplies status polls. A poll is
discarded if an event arrives while it is in flight. The actual subscription
adapter and feature ownership are separate concerns.
"""
import math,threading,time
from borrowed_gatt_view import TARGET,ADAPTER,valid_client

class ConnectedStatusWatch:
 def __init__(self,*,clock,max_age=3):
  if not callable(clock) or type(max_age) not in (int,float) or not math.isfinite(max_age) or not 0<max_age<=5:raise ValueError('invalid watch')
  self.clock=clock;self.max_age=max_age;self.lock=threading.Lock();self.changed=threading.Condition(self.lock);self.closed=False;self.acks=set();self.seq=0;self.generation=1;self.last=None;self.last_disconnected=None;self.last_connectable=None
 @staticmethod
 def valid(p):
  return (type(p) is dict and p.get('returnValue') is True and str(p.get('address','')).lower()==TARGET and str(p.get('adapterAddress','')).lower()==ADAPTER and
          type(p.get('connected')) is bool and type(p.get('connecting')) is bool and type(p.get('connectRequest')) is bool)
 @staticmethod
 def connected(p):return p['connected'] is True and p['connecting'] is False and p['connectRequest'] is False
 def event(self,role,p):
  with self.changed:
   self.changed.notify_all()
   if self.closed:return False
   if role not in ('hid','gatt') or not self.valid(p) or ('subscribed' in p and p['subscribed'] is not True):self.closed=True;self.last=None;return False
   if role not in self.acks:
    if p.get('subscribed') is not True:self.closed=True;self.last=None;return False
    self.acks.add(role)
   self.seq+=1;self.last_disconnected=None;self.last_connectable=None
   if not self.connected(p):self.generation+=1;self.last=None
   elif self.last is not None:
    # A benign connected update is common (e.g. service discovery). Keep the
    # other profile's original poll timestamp; this event must not extend its
    # freshness or turn an in-flight poll into a current observation.
    self.last={**self.last,role:dict(p),'sequence':self.seq}
   return True
 def begin_poll(self):
  with self.lock:return self.seq if not self.closed and self.acks=={'hid','gatt'} else None
 def is_open(self):
  with self.lock:return not self.closed
 def commit_poll(self,token,hid,gatt):
  with self.changed:
   self.changed.notify_all()
   if self.closed or type(token) is not int or token!=self.seq:return False
   if not self.valid(hid) or not self.valid(gatt):self.closed=True;self.last=None;return False
   now=self.clock()
   if type(now) not in (int,float) or not math.isfinite(now):self.closed=True;self.last=None;return False
   idle=lambda p:p['connected'] is False and p['connecting'] is False and p['connectRequest'] is False
   self.last_connectable={'hid':dict(hid),'gatt':dict(gatt),'generation':self.generation,'observedAt':now,'sequence':self.seq} if idle(hid) and (idle(gatt) or self.connected(gatt)) else None
   if not self.connected(hid) or not self.connected(gatt):
    self.last=None;self.generation+=1
    idle=lambda p:p['connected'] is False and p['connecting'] is False and p['connectRequest'] is False
    self.last_disconnected={'hid':dict(hid),'gatt':dict(gatt),'generation':self.generation,'observedAt':now,'sequence':self.seq} if idle(hid) and idle(gatt) else None
    return False
   self.last_disconnected=None;self.last_connectable=None;self.last={'hid':dict(hid),'gatt':dict(gatt),'generation':self.generation,'observedAt':now,'sequence':self.seq};return True
 def _snapshot_locked(self):
  if self.closed or self.last is None:return None
  now=self.clock();then=self.last['observedAt']
  if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now-then<=self.max_age:return None
  return {**self.last,'hid':dict(self.last['hid']),'gatt':dict(self.last['gatt'])}
 def snapshot(self):
  with self.lock:return self._snapshot_locked()
 def wait_for_connection(self,timeout,stop):
  """Wake a waiting supervisor after a fresh two-profile poll, not an event.

  The condition uses the same lock as publication, so a connection arriving
  between the caller's snapshot and this wait cannot be missed. The caller
  still takes a new snapshot and performs all admission checks afterward.
  """
  if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=.5:raise ValueError('Invalid connection wait')
  deadline=time.monotonic()+timeout
  with self.changed:
   while not self.closed and not stop.is_set():
    if self._snapshot_locked() is not None:return True
    remaining=deadline-time.monotonic()
    if remaining<=0:return False
    self.changed.wait(min(.05,remaining))
   return False
 def close(self):
  with self.changed:
   self.closed=True;self.last=None;self.last_disconnected=None;self.last_connectable=None
   self.changed.notify_all()
 def diagnostic(self,generation):
  """Non-authoritative metadata; never grants control or refreshes a poll."""
  with self.lock:
   age=None
   if self.closed:state='closed'
   elif self.generation!=generation:state='generation-changed'
   elif self.last is None:state='missing'
   else:
    delta=self.clock()-self.last['observedAt']
    if not math.isfinite(delta) or delta<0:state='clock-invalid'
    else:
     age=min(100000000,int(delta*1000))
     state='current' if delta<=self.max_age else 'stale'
   return {'watchState':state,'watchAgeMs':age}
 def connectable_snapshot(self):
  with self.lock:
   value=self.last_connectable
   if self.closed or value is None or not 0<=self.clock()-value['observedAt']<=self.max_age:return None
   return {**value,'hid':dict(value['hid']),'gatt':dict(value['gatt'])}
 def disconnected_snapshot(self):
  with self.lock:
   if self.closed or self.last_disconnected is None:return None
   now=self.clock();then=self.last_disconnected['observedAt']
   if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now-then<=self.max_age:return None
   return {**self.last_disconnected,'hid':dict(self.last_disconnected['hid']),'gatt':dict(self.last_disconnected['gatt'])}

class BoundConnectedView:
 """Bind a borrowed client to an already observed connection generation.

 The caller must independently determine the client ID. This does not prove
 ownership or detect a transition missed by the supplied status streams.
 """
 def __init__(self,watch,client_id):
  if not callable(getattr(watch,'snapshot',None)) or not valid_client(client_id):raise ValueError('invalid connection view')
  current=watch.snapshot()
  if type(current) is not dict or type(current.get('generation')) is not int:raise RuntimeError('connection unavailable')
  self.watch=watch;self.client_id=client_id;self.generation=current['generation']
 def snapshot(self):
  value=self.watch.snapshot()
  if type(value) is not dict or value.get('generation')!=self.generation:return None
  return {**value,'clientId':self.client_id}
