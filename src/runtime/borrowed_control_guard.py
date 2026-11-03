"""Bounded cooperative control evidence for a borrowed client.

The caller supplies live exact-profile snapshots and a generation which must
change when a link event is observed. This cannot detect an unobserved
disconnect/reconnect or exclude unrelated software.
"""
import math
from borrowed_gatt_view import TARGET,ADAPTER,valid_client

class BorrowedControlGuard:
 def __init__(self,*,generation,client_id,lease,profiles,clock,max_age=3):
  if type(generation) is not int or generation<=0 or not valid_client(client_id) or not callable(profiles) or not callable(clock) or not callable(getattr(lease,'held',None)) or type(max_age) not in (int,float) or not math.isfinite(max_age) or not 0<max_age<=5:raise ValueError('invalid guard')
  self.generation=generation;self.client_id=client_id;self.lease=lease;self.profiles=profiles;self.clock=clock;self.max_age=max_age;self.closed=False
  self.last_failure=None
 def _reject(self,reason):
  self.last_failure=reason;return False
 def __call__(self):
  if self.closed:return self._reject('closed')
  try:
   # The watcher may publish a newer observation concurrently. Sample time
   # after acquiring the snapshot so a valid newer observation is not falsely
   # rejected as being in the future.
   s=self.profiles()
   if self.lease.held() is not True:return self._reject('lease')
   if type(s) is not dict:return self._reject('snapshot')
   now=self.clock()
   if type(now) not in (int,float) or not math.isfinite(now):return self._reject('clock')
   at=s.get('observedAt')
   if type(at) not in (int,float) or not math.isfinite(at) or not 0<=now-at<=self.max_age:return self._reject('age')
   if s.get('generation')!=self.generation or type(s.get('generation')) is not int or s.get('clientId')!=self.client_id:return self._reject('identity')
   for name in ('hid','gatt'):
    p=s.get(name)
    if (type(p) is not dict or p.get('returnValue') is not True or str(p.get('address','')).lower()!=TARGET or str(p.get('adapterAddress','')).lower()!=ADAPTER or p.get('connected') is not True or p.get('connecting') is not False or p.get('connectRequest') is not False):return self._reject(name)
   if self.lease.held() is not True:return self._reject('lease')
   self.last_failure=None;return True
  except Exception:return self._reject('exception')
 def invalidate(self):self.closed=True
