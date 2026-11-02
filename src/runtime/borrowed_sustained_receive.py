"""Offline sustained receive over an active borrowed-mode session.

The caller supplies an exact verified target fd/output and is responsible for
sensor stop and all device closes. No device is opened on import.
"""
import math
from borrowed_mode_session import BorrowedModeSession
from rolling_receiver import RollingReceiver
from hid_input import receive_actions
from receive_diagnostics import capture

def receive_sustained(session,outputs,fd,*,duration,abort,clock,segment_seconds=300,read_fn=None,sleep_fn=None,stats=None,on_ready=None,system_key_emit=None,on_progress=None):
 if (type(session) is not BorrowedModeSession or session.state!='active' or type(fd) is not int or fd<0 or (duration is not None and (type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=7200)) or type(segment_seconds) not in (int,float) or not math.isfinite(segment_seconds) or not 30<segment_seconds<=7200 or not callable(abort) or not callable(clock) or (on_ready is not None and not callable(on_ready))):
  raise ValueError('invalid sustained session')
 if on_progress is not None and not callable(on_progress):raise ValueError('invalid progress callback')
 from receiver_progress import BoundedProgress
 progress=BoundedProgress(on_progress,clock=clock)
 end_reason=None;control_failure={}
 if stats is None:stats={}
 generation=getattr(session.view,'generation',None)
 if type(generation) is not int or generation<=0:raise ValueError('invalid connection generation')
 def live():
  try:
   ok=session.state=='active' and session.control_valid() is True
   if not ok and not control_failure:
    describe=getattr(session,'control_diagnostic',None)
    control_failure.update(describe() if callable(describe) else {})
    control_failure.setdefault('failure','session-inactive' if session.state!='active' else 'snapshot')
   return ok
  except Exception:
   if not control_failure:control_failure['failure']='exception'
   return False
 receiver=RollingReceiver(outputs,continuity=live,mode_verified=live,clock=clock,seconds=segment_seconds)
 if system_key_emit is not None:
  if not callable(system_key_emit):raise ValueError('system key emitter invalid')
  from combined_controls import CombinedControls
  receiver=CombinedControls(receiver,system_key_emit)
 receiver.start()
 try:
  if on_ready is not None and on_ready() is not True:raise RuntimeError('ready marker unconfirmed')
  def should_abort():
   nonlocal end_reason
   if receiver.closed:
    if end_reason is None:end_reason='control-or-policy-ended'
    return True
   value=abort()
   if type(value) is not bool:raise RuntimeError('invalid abort state')
   if value:end_reason='stop-requested'
   return value
  class Guarded:
   def tick(self):
    if should_abort():receiver.stop('receive-aborted')
    else:
     receiver.tick()
     if not receiver.closed:progress.maybe(receiver.summary)
   def feed_raw(self,gen,report):
    if should_abort():receiver.stop('receive-aborted');return False
    if type(gen) is not int or gen!=generation:return False
    return receiver.feed_raw(1,report)
  stats=receive_actions(fd,Guarded(),generation=generation,duration=duration,read_fn=read_fn,clock=clock,sleep_fn=sleep_fn,abort_fn=should_abort,stats=stats)
 except BaseException:
  if end_reason is None:end_reason='receive-exception'
  raise
 finally:
  try:receiver.stop('receive-ended')
  finally:
   # Retain the first failure before session.stop() changes the guard/view.
   capture(stats,receiver.summary(),end_reason or 'duration-ended',control_failure)
 if outputs.verify_released() is not True:raise RuntimeError('output-release-unverified')
 clean_stop=duration is None and end_reason=='stop-requested' and live()
 if type(stats) is not dict or (stats.get('aborted') is not False and not clean_stop) or type(stats.get('bytesReceived')) is not int or (stats['bytesReceived']<=0 and not clean_stop):raise RuntimeError('receive-unconfirmed')
 summary=receiver.summary()
 return {'status':'complete','bytesReceived':stats['bytesReceived'],'rotations':summary['rotations'],'outputsReleased':True,'endReason':end_reason or 'duration-ended'}
