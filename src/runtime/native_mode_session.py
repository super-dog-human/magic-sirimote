"""Connect an owned GATT client to the audited mode reader and stop path.

Finite sensor mode session only: no CCCD changes, input reads, cursor output,
pairing, HID connection or persistent registration. The caller supplies the
already-owned HID proof and the serialized process/control guard.
"""
from direct_gatt_read import TARGET,ADAPTER,HID_SERVICE,REPORT_CHAR,REPORT_REFERENCE,GET_SERVICES,READ_DESCRIPTORS,READ_CHARACTERISTICS,DirectGattReadProbe,_mode_candidate
from verified_mode_reader import VerifiedModeReader,EVIDENCE_SHA256
from pumping_luna_client import PumpingLunaClient,BASE,LunaCallError
from owned_settings_activation import PumpingGattActivationClient
from partial_activation_stop import PumpingGattPartialStopClient
from native_owned_gatt import NativeGattLease,NativeGattLeaseClient

SET='hid/internal/setReport'
class NativeModeClient(PumpingLunaClient):
 """Exact mode-only requests; CCCD changes are outside this client."""
 def __init__(self,*,generation,client_id,**kwargs):
  if type(generation) is not int or generation<=0 or type(client_id) is not str or not client_id.isascii() or not client_id.isdecimal() or not 1<=int(client_id)<=65535 or len(client_id)>5:raise ValueError('invalid mode context')
  super().__init__(native_app=True,**kwargs);self.client_id=client_id;self.generation=generation;self.counts={};self.enable_allowed=False
 def _validate_request(self,method,params,timeout):
  if type(method) is not str or type(params) is not dict:raise ValueError('invalid mode request')
  method=method.removeprefix(BASE);key=method
  if method==SET:
   data=params.get('reportData');key=SET+(':selector' if data==[240,240,160] else ':enable' if data==[240,160,1] else ':invalid')
  policies={
   GET_SERVICES.removeprefix(BASE):({'address':TARGET,'subscribe':False},5,1),
   READ_DESCRIPTORS.removeprefix(BASE):({'clientId':self.client_id,'service':HID_SERVICE,'characteristic':REPORT_CHAR,'descriptors':[REPORT_REFERENCE]},5,1),
   READ_CHARACTERISTICS.removeprefix(BASE):({'clientId':self.client_id,'service':HID_SERVICE,'characteristics':[REPORT_CHAR]},5,2),
   SET+':selector':({'address':TARGET,'reportType':'feature','reportData':[240,240,160]},5,1),
   SET+':enable':({'address':TARGET,'reportType':'feature','reportData':[240,160,1]},6,1),
  }
  if key not in policies:raise ValueError('mode request not allowed')
  expected,seconds,limit=policies[key]
  if not PumpingGattActivationClient._exact(params,expected) or type(timeout) not in (int,float) or timeout!=seconds:raise ValueError('mode request shape mismatch')
  if key==SET+':enable' and self.enable_allowed is not True:raise LunaCallError('mode zero not established')
  if self.counts.get(key,0)>=limit:raise LunaCallError('mode request budget consumed')
  self.counts[key]=self.counts.get(key,0)+1
  return method,seconds,False
def ack(reply):
 return (type(reply) is dict and reply.get('returnValue') is True and
         all(k not in reply or (type(reply[k]) is str and reply[k].lower()==v) for k,v in (('address',TARGET),('adapterAddress',ADAPTER))))

class NativeModeSession:
 def __init__(self,*,generation,hid_owned,control_valid,pump,guard,lease_factory=NativeGattLease,lease_client_factory=NativeGattLeaseClient,activation_factory=NativeModeClient,stop_factory=PumpingGattPartialStopClient,reader_factory=VerifiedModeReader):
  if type(generation) is not int or generation<=0 or hid_owned is not True or not all(callable(x) for x in (control_valid,pump,guard)):raise ValueError('owned HID generation and guards required')
  self.generation=generation;self.control_valid=control_valid;self.pump=pump;self.guard=guard;self.stop_factory=stop_factory;self.reader_factory=reader_factory;self.activation_factory=activation_factory
  self.lease=lease_factory(lease_client_factory(pump=pump,guard=guard,native_app=True),generation=generation,control_valid=control_valid)
  self.state='new';self.sensor_attempted=False;self.mode0_proven=False;self.baseline_zero=False;self.reader=None;self.client_id=None;self.stop_used=False
 def start(self):
  if self.state!='new' or self.control_valid() is not True:raise RuntimeError('invalid session state')
  self.state='starting'
  try:
   self.client_id=self.lease.connect();self.lease.discover()
   activation=self.activation_factory(generation=self.generation,client_id=self.client_id,pump=self.pump,guard=self.guard)
   self.reader=self.reader_factory(activation,audited_evidence_sha256=EVIDENCE_SHA256,exclusive_feature_access=True)
   link={'remote':TARGET,'adapter':ADAPTER,'generation':self.generation,'connected':True,'connecting':False,'paired':True}
   self.reader.bind(link=link,client_id=self.client_id,owned_hid=True,owned_gatt=True,control_valid=self.control_valid)
   if self.reader.read(self.generation).get('mode')!=0:raise RuntimeError('sensor-baseline-not-zero')
   self.baseline_zero=True
   if self.control_valid() is not True:raise RuntimeError('control-lost-before-enable')
   activation.enable_allowed=True
   self.sensor_attempted=True;self.mode0_proven=False
   if not ack(activation(SET,{'address':TARGET,'reportType':'feature','reportData':[240,160,1]},timeout=6)):raise RuntimeError('sensor-enable-unconfirmed')
   if self.reader.read(self.generation).get('mode')!=1:raise RuntimeError('sensor-enabled-state-unconfirmed')
   self.state='active';return {'status':'active','generation':self.generation,'sensorModeVerified':1}
  except Exception:
   self.state='attention';raise
 def stop(self):
  if self.stop_used:raise RuntimeError('stop already attempted')
  self.stop_used=True;result={'sensorDisableAttempted':False,'sensorDisableAcknowledged':False,'sensorModeZeroVerified':False,'gattReleaseAcknowledged':False,'status':'attention'}
  if self.control_valid() is not True:return result
  if self.sensor_attempted:
   stop=self.stop_factory(generation=self.generation,client_id=self.client_id,pump=self.pump,guard=self.guard,native_app=True)
   result['sensorDisableAttempted']=True
   try:result['sensorDisableAcknowledged']=ack(stop(SET,{'address':TARGET,'reportType':'feature','reportData':[240,160,0]},timeout=6))
   except Exception:pass
   if self.reader is not None and self.reader.reference_verified and self.reader.selector_attempts==1 and self.control_valid() is True:
    try:
     reply=stop(READ_CHARACTERISTICS,{'clientId':self.client_id,'service':HID_SERVICE,'characteristics':[REPORT_CHAR]},timeout=5)
     if DirectGattReadProbe._reply_ok(reply) and DirectGattReadProbe._identity(reply,self.client_id):
      data=DirectGattReadProbe._extract_candidate(reply);candidate=None if data is None else _mode_candidate(data)
      result['sensorModeZeroVerified']=candidate=={'framing':'A0-mode','mode':0,'status':'candidate_only'}
    except Exception:pass
   self.mode0_proven=result['sensorModeZeroVerified']
  else:self.mode0_proven=self.baseline_zero;result['sensorModeZeroVerified']=self.baseline_zero
  release_safe=self.mode0_proven or not self.sensor_attempted
  if release_safe and self.lease.state in ('owned','discovered','discover-unknown') and self.control_valid() is True:
   try:result['gattReleaseAcknowledged']=self.lease.release() is True
   except Exception:pass
  if release_safe and result['gattReleaseAcknowledged']:
   self.state='stopped';result['status']='stopped' if self.mode0_proven else 'released-without-sensor-change'
  else:self.state='attention'
  return result
