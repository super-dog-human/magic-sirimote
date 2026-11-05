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


class ReconnectIdentityRead(PumpingLunaClient):
 """One read on an isolated transport; never a connect or a Feature request."""
 # A failed optional read must not poison the receiver's command transport.
 # The existing subprocess path reaps the exact reader before returning.
 _shared_native_transport=False
 def __init__(self,client_id,**kwargs):
  from borrowed_gatt_view import valid_client
  if not valid_client(client_id):raise ValueError('invalid reconnect client')
  super().__init__(native_app=True,**kwargs);self.client_id=client_id;self.used=False
 def _validate_request(self,method,params,timeout):
  from battery_status import SERVICE,LEVEL
  expected={'clientId':self.client_id,'service':SERVICE,'characteristics':[LEVEL]}
  if method!='gatt/readCharacteristicValues' or params!=expected or type(timeout) not in (int,float) or timeout!=1:
   raise ValueError('request outside reconnect identity read')
  if self.used:raise LunaCallError('reconnect identity read consumed')
  self.used=True;return method,1,False


def revalidate_client(reply,*,watch,lease,requester_factory=ReconnectIdentityRead,clock=None,record=None):
 """Refresh a same-worker client hint through a read on the new connection.

 Only identity is reused; mode zero and input admission remain separate. A
 failed read can fall back only after its subprocess is confirmed stopped and
 the original connection generation/owner is still valid.
 """
 import math,time
 from borrowed_gatt_view import ADAPTER
 from pumping_luna_client import LunaChildStopError
 from battery_status import SERVICE,LEVEL,percentage
 clock=clock or time.monotonic
 started=clock()
 def note(outcome,**detail):
  if record is not None:record('revalidation',{'outcome':outcome,'elapsedMs':max(0,int((clock()-started)*1000)),**detail})
 if reply is None:
  note('missing-hint');return None
 try:BorrowedGattView(reply,generation=1,control_valid=lambda:False,discover=lambda _:None)
 except (ValueError,TypeError):
  note('invalid-hint');return None
 current=watch.snapshot()
 if type(current) is not dict or type(current.get('generation')) is not int:
  note('missing-generation');return None
 generation=current['generation']
 def guard():
  value=watch.snapshot();now=clock()
  return (lease.held() is True and watch.is_open() is True and type(value) is dict
          and value.get('generation')==generation
          and type(now) in (int,float) and math.isfinite(now)
          and type(value.get('observedAt')) in (int,float)
          and 0<=now-value['observedAt']<=3)
 if not guard():
  note('control-unavailable');return None
 request=requester_factory(reply['clientId'],pump=lambda:None,guard=guard)
 try:
  value=request('gatt/readCharacteristicValues',{'clientId':reply['clientId'],'service':SERVICE,'characteristics':[LEVEL]},timeout=1)
 except LunaChildStopError:raise
 except (LunaCallError,OSError) as error:
  if not guard():raise RuntimeError('reconnect identity control lost')
  reasons={'Native application identity unverified':'app-identity','Call guard rejected dispatch':'guard',
           'Luna call timed out':'timeout','Luna response was not a single object':'response-format'}
  note('transport-failed',reason=reasons.get(str(error),'other'),errorType=type(error).__name__)
  return None
 if not guard():raise RuntimeError('reconnect identity control lost')
 try:percentage(value,TARGET,ADAPTER,reply['clientId'])
 except ValueError:
  detail={}
  if type(value) is dict:
   detail['replyAccepted']=value.get('returnValue') is True
   code=value.get('errorCode')
   if type(code) is int and 0<=code<=9999:detail['errorCode']=code
  note('response-not-validated',**detail);return None
 note('verified')
 # This is a newly validated association, not a fabricated connect response.
 return {'returnValue':True,'address':value['address'],'adapterAddress':value['adapterAddress'],
         'clientId':reply['clientId']},generation
