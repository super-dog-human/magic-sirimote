"""Receiver-side view of the controller's existing authenticated status watcher.

No Bluetooth subscriptions, status calls, or timestamps are created here. The
source observation keeps its original time and connection generation. A lost
handoff or changed generation closes this view permanently for this session.
"""
import math,threading,time
from connected_status_watch import ConnectedStatusWatch

PROFILE_KEYS=('returnValue','address','adapterAddress','connected','connecting','connectRequest')

def select_observation(value,*,clock=time.monotonic,max_age=3):
 if type(value) is not dict or set(value)!={'generation','observedAt','sequence','hid','gatt'}:raise ValueError('invalid controller observation')
 if type(value['generation']) is not int or value['generation']<1 or type(value['sequence']) is not int or value['sequence']<0:raise ValueError('invalid controller generation')
 at=value['observedAt'];now=clock()
 if any(type(x) not in (int,float) or not math.isfinite(x) for x in (at,now)) or not 0<=now-at<=max_age:raise RuntimeError('stale controller observation')
 result={key:value[key] for key in ('generation','observedAt','sequence')}
 for role in ('hid','gatt'):
  profile=value[role]
  if not ConnectedStatusWatch.valid(profile) or not ConnectedStatusWatch.connected(profile):raise RuntimeError('controller profile unavailable')
  result[role]={key:profile[key] for key in PROFILE_KEYS}
 return result

class ControllerStatusWatch:
 def __init__(self,client,*,clock=time.monotonic,period=.5):
  if not callable(getattr(client,'observe',None)) or not callable(clock) or type(period) not in (int,float) or not 0<period<=.5:raise ValueError('invalid controller watcher')
  self.client=client;self.clock=clock;self.period=period;self.max_age=3;self.tracker=self
  self.stop_event=threading.Event();self.lock=threading.Lock();self.thread=None
  self.closed=False;self.last=None;self.generation=None
 def _close(self):
  with self.lock:self.closed=True;self.last=None
  self.stop_event.set()
 def _refresh(self):
  try:
   value=select_observation(self.client.observe(),clock=self.clock,max_age=self.max_age)
   with self.lock:
    if self.closed:return False
    if self.generation is not None and value['generation']!=self.generation:raise RuntimeError('controller generation changed')
    self.generation=value['generation'];self.last=value
   return True
  except Exception:
   self._close();return False
 def _run(self):
  while not self.stop_event.is_set():
   if not self._refresh():return
   self.stop_event.wait(self.period)
 def start(self):
  if self.thread is not None or self.closed:raise RuntimeError('controller watcher already used')
  self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
 def snapshot(self):
  with self.lock:
   if self.closed or self.last is None:return None
   try:return select_observation(self.last,clock=self.clock,max_age=self.max_age)
   except (ValueError,RuntimeError):return None
 def is_open(self):
  with self.lock:return not self.closed
 def diagnostic(self,generation):
  with self.lock:
   age=None
   if self.closed:state='closed'
   elif self.generation is not None and self.generation!=generation:state='generation-changed'
   elif self.last is None:state='missing'
   else:
    delta=self.clock()-self.last['observedAt']
    if not math.isfinite(delta) or delta<0:state='clock-invalid'
    else:
     age=min(100000000,int(delta*1000));state='current' if delta<=self.max_age else 'stale'
   return {'watchState':state,'watchAgeMs':age}
 def stop(self,timeout=2):
  self._close()
  if self.thread is not None:
   self.thread.join(timeout)
   return not self.thread.is_alive()
  return True
