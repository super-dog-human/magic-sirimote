"""Sensor lifecycle using an unowned GATT view.

The injected reader, writer and control guard must independently establish
exact device identity, current client/generation and exclusive feature
access. This module alone proves none of them.
"""

class BorrowedModeSession:
 def __init__(self,view,*,read_mode,read_stop_mode,write_mode,control_valid,record):
  if not all(callable(x) for x in (read_mode,read_stop_mode,write_mode,control_valid,record)) or not callable(getattr(view,'close',None)):raise ValueError('invalid dependencies')
  self.view=view;self.read_mode=read_mode;self.read_stop_mode=read_stop_mode;self.write_mode=write_mode;self.control_valid=control_valid;self.record=record
  self.state='new';self.enable_attempted=False;self.stop_attempted=False
 def start(self):
  if self.state!='new' or self.control_valid() is not True:raise RuntimeError('control-unavailable')
  self.state='starting'
  try:
   mode=self.read_mode()
   if type(mode) is not int or mode!=0 or self.control_valid() is not True:raise RuntimeError('baseline-not-zero')
   permit=getattr(self.write_mode,'permit_enable',None)
   if callable(permit):permit()
   if self.record({'stage':'sensor-enable-intent'}) is not True:raise RuntimeError('enable intent not recorded')
   self.enable_attempted=True
   if self.write_mode(1) is not True:raise RuntimeError('enable-unconfirmed')
   if self.record({'stage':'sensor-enable-ack'}) is not True:raise RuntimeError('enable acknowledgement not recorded')
   if self.control_valid() is not True:raise RuntimeError('control-lost-after-enable')
   mode=self.read_mode()
   if type(mode) is not int or mode!=1 or self.control_valid() is not True:raise RuntimeError('enable-readback-unconfirmed')
   self.state='active';return {'status':'active','mode':1,'clientOwnership':'unproven'}
  except BaseException:
   self.state='attention';raise
 def stop(self):
  if self.stop_attempted:raise RuntimeError('stop-already-attempted')
  refresh=getattr(self,'battery_refresh',None)
  if refresh is not None:refresh.close()
  self.stop_attempted=True
  out={'status':'attention','disableAttempted':False,'modeZeroVerified':False,'gattDisconnectCalls':0,'clientOwnership':'unproven'}
  try:
   if self.control_valid() is not True:return out
   if self.enable_attempted:
    if self.record({'stage':'sensor-stop-intent'}) is not True:return out
    out['disableAttempted']=True
    try:self.write_mode(0)
    except Exception:pass
   if self.control_valid() is not True:return out
   mode=self.read_stop_mode()
   if type(mode) is int and mode==0 and self.control_valid() is True:
    out['modeZeroVerified']=True
    if self.enable_attempted and self.record({'stage':'sensor-zero-confirmed'}) is not True:return out
    out['status']='stopped'
   return out
  finally:
   # Closing the view only releases local resources, never the shared link.
   self.view.close();self.state='stopped' if out['status']=='stopped' else 'attention'
