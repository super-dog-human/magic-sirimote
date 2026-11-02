"""One caller-owned GATT client for the native receiver; no work on import.

This does not own the already-established physical GATT link. A rejected or
unknown client release is not proof of link restoration. Sensor writes and
input are outside this module.
"""
from pumping_luna_client import PumpingLunaClient,LunaCallError
from direct_gatt_read import TARGET,ADAPTER

def client_id(value):
 return type(value) is str and value.isascii() and value.isdecimal() and 1<=len(value)<=5 and 1<=int(value)<=65535

class NativeGattLeaseClient(PumpingLunaClient):
 def __init__(self,**kwargs):
  if kwargs.pop('native_app',True) is not True:raise ValueError('native app identity required')
  super().__init__(native_app=True,**kwargs);self.counts={'connect':0,'discover':0,'disconnect':0};self.owned_client=None
 def _validate_request(self,method,params,timeout):
  names={'gatt/connect':'connect','gatt/discoverServices':'discover','gatt/disconnect':'disconnect'}
  name=names.get(method)
  if name is None or type(params) is not dict:raise ValueError('method outside GATT lease')
  expected={'connect':({'address':TARGET,'subscribe':False},12),'discover':({'address':TARGET},8),'disconnect':({'clientId':self.owned_client},8)}
  wanted,seconds=expected[name]
  if params!=wanted or type(timeout) not in (int,float) or timeout!=seconds:raise ValueError('invalid target or timeout')
  if name!='connect' and self.owned_client is None:raise LunaCallError('no confirmed owned client')
  if self.counts[name]:raise LunaCallError('GATT lease operation already attempted')
  self.counts[name]+=1
  return method,seconds,False

class NativeGattLease:
 def __init__(self,client,*,generation,control_valid):
  if type(client) is not NativeGattLeaseClient or type(generation) is not int or generation<=0 or not callable(control_valid):raise ValueError('exact client and generation required')
  self.client=client;self.generation=generation;self.control_valid=control_valid;self.state='new';self.own=None
 def connect(self):
  if self.state!='new' or self.control_valid() is not True:raise RuntimeError('connection context invalid')
  self.state='connect-unknown'
  reply=self.client('gatt/connect',{'address':TARGET,'subscribe':False},timeout=12)
  if (type(reply) is not dict or reply.get('returnValue') is not True or not client_id(reply.get('clientId')) or str(reply.get('address','')).lower()!=TARGET or str(reply.get('adapterAddress','')).lower()!=ADAPTER):raise RuntimeError('client ownership unconfirmed')
  self.own=reply['clientId'];self.client.owned_client=self.own;self.state='owned'
  return self.own
 def discover(self):
  if self.state!='owned' or self.control_valid() is not True:raise RuntimeError('owned connection invalid')
  self.state='discover-unknown';reply=self.client('gatt/discoverServices',{'address':TARGET},timeout=8)
  if type(reply) is not dict or reply.get('returnValue') is not True:raise RuntimeError('discovery unconfirmed')
  self.state='discovered';return True
 def release(self):
  if self.state not in ('owned','discovered','discover-unknown') or self.own is None or self.control_valid() is not True:raise RuntimeError('owned client release unavailable')
  self.state='release-unknown';reply=self.client('gatt/disconnect',{'clientId':self.own},timeout=8)
  if type(reply) is not dict or reply.get('returnValue') is not True or ('clientId' in reply and reply['clientId']!=self.own):raise RuntimeError('owned client release unconfirmed')
  self.state='released';return True
