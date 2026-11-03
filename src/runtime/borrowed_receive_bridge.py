"""Finite, composition with the existing HID receive loop.

The caller owns validated device handles, a live status pump and the
borrowed session. This does not open or close device handles, install, or
auto-start.
"""
import math
from borrowed_motion_gate import BorrowedMotionGate
from hid_input import receive_actions

def receive_once(session,receiver,fd,*,duration,abort,read_fn=None,clock=None,sleep_fn=None,stats=None,on_ready=None):
 if type(fd) is not int or fd<0 or type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=60 or not callable(abort) or (on_ready is not None and not callable(on_ready)):raise ValueError('invalid finite receiver')
 gate=BorrowedMotionGate(receiver,session)
 try:
  if on_ready is not None and on_ready() is not True:raise RuntimeError('ready marker unconfirmed')
  def should_abort():
   if gate.closed:return True
   value=abort()
   if type(value) is not bool:raise RuntimeError('invalid abort state')
   return value
  class GuardedInput:
   def tick(self):
    if should_abort():gate.stop('receive-aborted')
    else:gate.tick()
   def feed_raw(self,generation,report):
    if should_abort():gate.stop('receive-aborted');return False
    return gate.feed_raw(generation,report)
  stats=receive_actions(fd,GuardedInput(),generation=gate.generation,duration=duration,read_fn=read_fn,clock=clock,sleep_fn=sleep_fn,abort_fn=should_abort,stats=stats)
 finally:
  gate.stop('receive-ended')
 if receiver.outputs.verify_released() is not True:raise RuntimeError('output-release-unverified')
 if (type(stats) is not dict or stats.get('aborted') is not False or type(stats.get('bytesReceived')) is not int or stats['bytesReceived']<=0):raise RuntimeError('receive-unconfirmed')
 return {'status':'complete','bytesReceived':stats['bytesReceived'],'motionGateOpened':gate.opened,'outputsReleased':True}
