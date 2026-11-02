"""One bounded F0/AF input-start request for a live borrowed connection.

The effect on current target firmware and recovery from an unknown result are
not established. No retry or disconnect is performed by this adapter.
"""
from pumping_luna_client import PumpingLunaClient,LunaCallError
from borrowed_gatt_view import TARGET,ADAPTER

class BorrowedInputStart(PumpingLunaClient):
 def __init__(self,**kwargs):
  super().__init__(native_app=True,**kwargs);self.attempts=0
 def _validate_request(self,method,params,timeout):
  expected={'address':TARGET,'reportType':'feature','reportData':[240,175]}
  if method!='hid/internal/setReport' or type(params) is not dict or params!=expected or timeout!=8:raise ValueError('invalid input start request')
  if self.attempts:raise LunaCallError('input start already attempted')
  self.attempts+=1
  return method,8,True
 def start(self):
  reply=self('hid/internal/setReport',{'address':TARGET,'reportType':'feature','reportData':[240,175]},timeout=8)
  if type(reply) is not dict or reply.get('returnValue') is not True or str(reply.get('address','')).lower()!=TARGET or str(reply.get('adapterAddress','')).lower()!=ADAPTER:raise RuntimeError('input start unconfirmed')
  return True
