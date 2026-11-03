"""Bounded client lookup for an already-observed GATT connection.

An accepted response is explicitly *not* proof of client ownership. Calling
connect may create resources on implementations unlike the OSE example;
there is no automatic retry or disconnect.
"""
from pumping_luna_client import PumpingLunaClient,LunaCallError
from borrowed_gatt_view import BorrowedGattView,TARGET

class BorrowedGattRequester(PumpingLunaClient):
 def __init__(self,**kwargs):
  super().__init__(native_app=True,**kwargs);self.counts={'connect':0,'discover':0};self.view=None
 def _validate_request(self,method,params,timeout):
  allowed={'gatt/connect':({'address':TARGET,'subscribe':False},12),'gatt/discoverServices':({'address':TARGET},8)}
  if method not in allowed:raise ValueError('method outside borrowed lookup')
  expected,seconds=allowed[method]
  if type(params) is not dict or params!=expected or type(timeout) not in (int,float) or timeout!=seconds:raise ValueError('request mismatch')
  key='connect' if method=='gatt/connect' else 'discover'
  if self.counts[key] or (key=='discover' and self.view is None):raise LunaCallError('lookup budget or view invalid')
  self.counts[key]+=1
  # No automatic retry or disconnect, including an unknown connect result.
  return method,seconds,False
 def borrow(self,*,generation,control_valid):
  if type(generation) is not int or generation<=0 or not callable(control_valid) or control_valid() is not True:raise RuntimeError('connected control required')
  reply=self('gatt/connect',{'address':TARGET,'subscribe':False},timeout=12)
  if control_valid() is not True:raise RuntimeError('control changed after lookup')
  if type(reply) is dict and reply.get('returnValue') is False:
   code=reply.get('errorCode')
   if type(code) is int and 0<=code<=9999:raise RuntimeError('gatt-rejected-'+str(code))
   raise RuntimeError('gatt-rejected-unknown')
  view=BorrowedGattView(reply,generation=generation,control_valid=control_valid,
                        discover=lambda params:self('gatt/discoverServices',params,timeout=8))
  self.view=view;return view
 def adopt(self,reply,*,generation,control_valid):
  """Use an authenticated controller reply without another connect call."""
  if self.view is not None or self.counts['connect'] or self.counts['discover'] or control_valid() is not True:raise RuntimeError('borrowed handoff unavailable')
  view=BorrowedGattView(reply,generation=generation,control_valid=control_valid,
                        discover=lambda params:self('gatt/discoverServices',params,timeout=8))
  self.counts['connect']=1  # Reserve the budget; no reconnect fallback.
  self.view=view;return view
