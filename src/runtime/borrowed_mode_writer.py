"""Bounded mode-only writer using distinct activation and stop clients.

The caller must verify mode zero before permitting an enable. No pairing,
client disconnect, selector, input, or CCCD operation is offered here.
"""
from native_mode_session import ack

class BorrowedModeWriter:
 def __init__(self,activation,stop,*,guard):
  if not callable(activation) or not callable(stop) or not callable(guard):raise ValueError('invalid mode writer')
  self.activation=activation;self.stop_client=stop;self.guard=guard;self.permitted=False;self.enabled=False;self.stopped=False
 def permit_enable(self):
  if self.permitted or self.enabled or self.guard() is not True:raise RuntimeError('enable permission unavailable')
  self.permitted=True
 def __call__(self,mode):
  if type(mode) is not int or mode not in (0,1) or self.guard() is not True:raise RuntimeError('mode control unavailable')
  if mode==1:
   if not self.permitted or self.enabled:raise RuntimeError('enable not permitted')
   self.enabled=True;self.activation.enable_allowed=True
   reply=self.activation('hid/internal/setReport',{'address':'02:00:00:00:00:01','reportType':'feature','reportData':[240,160,1]},timeout=6)
  else:
   if not self.enabled or self.stopped:raise RuntimeError('stop not permitted')
   self.stopped=True
   reply=self.stop_client('hid/internal/setReport',{'address':'02:00:00:00:00:01','reportType':'feature','reportData':[240,160,0]},timeout=6)
  return ack(reply)
