"""Offline model of subscription-backed HID/GATT continuity.

Events and polling must be supplied by a future device adapter. This model
does not itself subscribe, and cannot prove that the TV delivered every event.
Any ambiguous update invalidates this generation permanently.
"""
import math,threading
from borrowed_gatt_view import TARGET,ADAPTER,valid_client

class ProfileContinuity:
 def __init__(self,*,generation,client_id,clock):
  if type(generation) is not int or generation<=0 or not valid_client(client_id) or not callable(clock):raise ValueError('invalid continuity identity')
  self.generation=generation;self.client_id=client_id;self.clock=clock;self.lock=threading.Lock();self.closed=False;self.acks=set();self.last=None
 @staticmethod
 def valid(value):
  return (type(value) is dict and value.get('returnValue') is True and
          str(value.get('address','')).lower()==TARGET and str(value.get('adapterAddress','')).lower()==ADAPTER and
          value.get('connected') is True and value.get('connecting') is False and value.get('connectRequest') is False)
 def event(self,role,value):
  with self.lock:
   if self.closed:return False
   if role not in ('hid','gatt') or not self.valid(value) or ('subscribed' in value and value['subscribed'] is not True):self.closed=True;return False
   if role not in self.acks:
    if value.get('subscribed') is not True:self.closed=True;return False
    self.acks.add(role)
   return True
 def poll(self,hid,gatt):
  with self.lock:
   if self.closed:return False
   if self.acks!={'hid','gatt'} or not self.valid(hid) or not self.valid(gatt):self.closed=True;return False
   now=self.clock()
   if type(now) not in (int,float) or not math.isfinite(now) or (self.last is not None and now<self.last['observedAt']):self.closed=True;return False
   self.last={'hid':dict(hid),'gatt':dict(gatt),'clientId':self.client_id,'generation':self.generation,'observedAt':now};return True
 def snapshot(self):
  with self.lock:
   if self.closed or self.last is None:return None
   return {**self.last,'hid':dict(self.last['hid']),'gatt':dict(self.last['gatt'])}
 def acknowledged(self):
  with self.lock:return not self.closed and self.acks=={'hid','gatt'}
 def close(self):
  with self.lock:self.closed=True;self.last=None
