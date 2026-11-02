"""Interpret scan subscription messages without retaining device payloads.

The webOS OSE API distinguishes a detected/changed `device` from the
`devices` array of known devices. OSE also asks its adapter to match devices
against the filter immediately after subscription, so even an individual
event must not be assumed to be a new radio advertisement. This filter does
not start a scan, authenticate a wake or establish TV firmware compatibility.
"""
import math,time
from tv_bluetooth import TARGET,ADAPTER

class TargetScanWake:
 def __init__(self,*,clock=time.monotonic,max_age=5):
  if not callable(clock) or type(max_age) not in (int,float) or not math.isfinite(max_age) or not 0<max_age<=10:raise ValueError('invalid wake gate')
  self.clock=clock;self.max_age=max_age;self.ready=False;self.observed=None;self.closed=False
 def accept(self,message):
  if self.closed or type(message) is not dict:return False
  if message.get('returnValue') is not True:self.closed=True;return False
  if 'subscribed' in message and message['subscribed'] is not True:self.closed=True;return False
  root_adapter=message.get('adapterAddress')
  if root_adapter not in (None,'') and (type(root_adapter) is not str or root_adapter.lower()!=ADAPTER):self.closed=True;return False
  if message.get('subscribed') is True:self.ready=True
  device=message.get('device')
  if not self.ready or type(device) is not dict:return False
  address=device.get('address');adapter=device.get('adapterAddress')
  if type(address) is not str or address.lower()!=TARGET:return False
  if adapter not in (None,'') and (type(adapter) is not str or adapter.lower()!=ADAPTER):return False
  now=self.clock()
  if type(now) not in (int,float) or not math.isfinite(now):self.closed=True;return False
  self.observed=now;return True
 def consume(self):
  if self.closed or self.observed is None:return False
  now=self.clock();then=self.observed;self.observed=None
  if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now-then<=self.max_age:return False
  return True
 def close(self):self.closed=True;self.observed=None
