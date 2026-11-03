"""FC21 output through grouped relative-motion packets.

No device opens. Caller provides already-verified output descriptors. The
caller also authenticates the live sensor stream.
"""
from prefix_output_candidate import PrefixOutputCandidate
from nonblocking_relative_transport import NonblockingRelativeTransport
from output_bridge import EVENT
from relative_grouped_packets import encode_neutral_cursor_flush, encode_grouped_relative_batch, RelativePacketBudgetExceeded

class GroupedPrefixOutput(PrefixOutputCandidate):
 def __init__(self,outputs,*,clock,sensor_input_verified=False,session_policy=None,max_actions=12,action_history_limit=None):
  super().__init__(outputs,clock=clock,sensor_input_verified=sensor_input_verified,session_policy=session_policy,max_actions=max_actions,action_history_limit=action_history_limit)
  seconds=30. if session_policy is None else session_policy.seconds
  self.transport=NonblockingRelativeTransport(self._write_grouped,self._deliver,clock=clock,generation=1,max_seconds=seconds,session_policy=session_policy)
  self.transport_token=1
  self.motion_budget_drops=0
 def _write_grouped(self,packet):
  if self.outputs.failed or self.outputs.closed:raise RuntimeError('output-bridge-not-active')
  if type(packet) is not bytes or not packet or len(packet)%EVENT.size or len(packet)>2256:raise ValueError('invalid grouped packet')
  events=list(EVENT.iter_unpack(packet));group=0
  for sec,usec,kind,code,value in events:
   if sec!=0 or usec!=0:raise ValueError('nonzero timestamp')
   if kind==2 and code in (0,1) and value!=0 and abs(value)<=15:
    group+=1
    if group>10:raise ValueError('too many grouped axes')
   elif (kind,code,value)==(0,0,0) and group>0:group=0
   else:raise ValueError('unexpected grouped event')
  if group or events[-1][2:]!=(0,0,0):raise ValueError('unterminated grouped packet')
  try:
   n=self.outputs.write_fn(self.outputs.mouse_fd,packet)
   if n!=len(packet):raise OSError('short write')
   if packet!=encode_neutral_cursor_flush():self.outputs.motion_writes+=1
   return n
  except BaseException:self.outputs.failed=True;raise
 def _deliver(self,action,down):
  super()._emit(action,down)
  return True
 def _emit(self,action,down):
  if down and action in ('up','down','left','right'):
   # Discard old unsent cursor motion; complete any written neutral tail
   # before the direction key so no cursor packet follows that switch.
   self._check_transport(self.transport.discard_queued_motion(self.transport_token))
  if not self.transport.semantic(self.transport_token,action,down):
   raise RuntimeError('grouped semantic output unavailable')
  return True
 def _check_transport(self,ok):
  if not ok and self.transport.closed:
   raise RuntimeError('grouped transport closed: '+str(self.transport.reason))
 def _discard_untracked(self):
  if self.router.pose.last_pose is None and self.transport.queue:
   self._check_transport(self.transport.discard_queued_motion(self.transport_token))
 def feed_raw(self,generation,report):
  accepted=super().feed_raw(generation,report)
  if not self.closed:
   try:self._discard_untracked()
   except BaseException:self.failed=True;self._stop_after_error();raise
  return accepted
 def tick(self):
  if self.closed:raise RuntimeError('receiver-closed')
  try:
   delta=self.router.tick();self._discard_untracked()
   # Finish the previous frame before a new body can postpone its neutral tail.
   self._check_transport(self.transport.pump(self.transport_token))
   if delta is not None and self.bridge.sensor_input_verified:
    # A large valid pose step is not an output-device failure. Discard it and
    # rebase tracking rather than increasing the write budget or replaying it.
    # Validate before transport.motion(), which closes on an encoding failure.
    try:encode_grouped_relative_batch(*delta)
    except RelativePacketBudgetExceeded:
     self.motion_budget_drops+=1;self.router.pose._clear_tracking();self._discard_untracked()
    else:self._check_transport(self.transport.motion(self.transport_token,*delta))
  except BaseException:self.failed=True;self._stop_after_error();raise
 def stop(self,reason='receiver-stop'):
  if self.closed:return
  self.closed=True
  try:self.router.stop(reason)
  finally:
   try:
    if not self.transport.closed:self.transport.stop(self.transport_token)
   finally:
    if not self.outputs.best_effort_release():raise RuntimeError('output-release-unverified')
 def summary(self):
  result=super().summary();result['relativeEncoding']='grouped-idle-neutral';result['transport']=self.transport.summary();result['motionBudgetDrops']=self.motion_budget_drops;return result
