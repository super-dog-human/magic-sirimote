"""Offline bridge from a live borrowed mode session to the input router.

This does not acquire a device, install a service, or prove exclusive access.
The session's live guard and mode readback remain prerequisites. A valid
motion frame establishes frame shape, not calibration or physical accuracy.
"""
from borrowed_mode_session import BorrowedModeSession
from combined_receiver import CombinedReceiver
from hidraw_frame_demux import demux_report, MOTION_REPORT_LENGTHS

class BorrowedMotionGate:
 def __init__(self,receiver,session):
  if type(receiver) is not CombinedReceiver or type(session) is not BorrowedModeSession:
   raise ValueError('expected receiver and session')
  generation=getattr(session.view,'generation',None)
  if (type(generation) is not int or generation<=0 or session.state!='active'
      or receiver.closed or receiver.generation!=generation
      or receiver.bridge.sensor_input_verified is not False
      or session.control_valid() is not True):
   raise ValueError('active current session required')
  self.receiver=receiver;self.session=session;self.generation=generation
  self.closed=False;self.opened=False;self.complete_frames=0
 def _live(self):
  try:return self.session.state=='active' and self.session.control_valid() is True
  except Exception:return False
 def _check_live(self):
  if self.closed:return False
  if not self._live():self.stop('borrowed-control-lost');return False
  return True
 def feed_raw(self,generation,report):
  if not self._check_live() or type(generation) is not int or generation!=self.generation:return False
  if type(report) is bytes and len(report) in MOTION_REPORT_LENGTHS and demux_report(report) is not None:
   self.complete_frames+=1
   if not self.opened:self.receiver.bridge.sensor_input_verified=True;self.opened=True
  return self.receiver.feed_raw(generation,report)
 def tick(self):
  if self._check_live():self.receiver.tick()
 def stop(self,reason='requested'):
  if self.closed:return
  self.closed=True;self.receiver.bridge.sensor_input_verified=False;self.receiver.stop(reason)
 def summary(self):
  out=self.receiver.summary();out['motionEvidence']={'motionGateOpened':self.opened,'completeFrames':self.complete_frames,'closed':self.closed,'rawReportsStored':False};return out
