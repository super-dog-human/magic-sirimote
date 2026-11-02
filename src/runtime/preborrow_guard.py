"""Validate an observed connection before obtaining any GATT client ID.

This is cooperative local control plus a caller-supplied external feature
guard, not proof that arbitrary TV software cannot change the connection.
"""
import math
from borrowed_gatt_view import TARGET,ADAPTER

class PreBorrowGuard:
 def __init__(self,watch,lease,*,generation,external_feature_guard,clock,max_age=3):
  if type(generation) is not int or generation<=0 or not callable(getattr(watch,'snapshot',None)) or not callable(getattr(lease,'held',None)) or not callable(external_feature_guard) or not callable(clock) or type(max_age) not in (int,float) or not math.isfinite(max_age) or not 0<max_age<=5:raise ValueError('invalid pre-borrow guard')
  self.watch=watch;self.lease=lease;self.generation=generation;self.external=external_feature_guard;self.clock=clock;self.max_age=max_age;self.last_failure=None
 def __call__(self):
  try:
   s=self.watch.snapshot();now=self.clock()
   if self.lease.held() is not True:self.last_failure='lease';return False
   if self.external() is not True:self.last_failure='feature';return False
   if type(s) is not dict or s.get('generation')!=self.generation or type(s.get('generation')) is not int:self.last_failure='snapshot';return False
   at=s.get('observedAt')
   if type(now) not in (int,float) or type(at) not in (int,float) or not math.isfinite(now) or not math.isfinite(at) or not 0<=now-at<=self.max_age:self.last_failure='age';return False
   for role in ('hid','gatt'):
    p=s.get(role)
    if type(p) is not dict or p.get('returnValue') is not True or str(p.get('address','')).lower()!=TARGET or str(p.get('adapterAddress','')).lower()!=ADAPTER or p.get('connected') is not True or p.get('connecting') is not False or p.get('connectRequest') is not False:self.last_failure=role;return False
   self.last_failure=None;return True
  except Exception:self.last_failure='exception';return False
