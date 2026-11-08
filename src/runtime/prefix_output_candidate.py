"""Adapter to the existing verified-output boundary.

The caller must separately establish target and sensor authorization. The
flag is a synthetic-test gate, not proof that real FC21 data is orientation.
"""
from combined_receiver import CombinedReceiver
from adaptive_prefix_router import AdaptivePrefixRouter

class PrefixOutputCandidate(CombinedReceiver):
 def __init__(self,outputs,*,clock,sensor_input_verified=False,session_policy=None,max_actions=12,action_history_limit=None):
  if type(sensor_input_verified) is not bool:raise ValueError('explicit gate required')
  super().__init__(outputs,clock=clock,sensor_input_verified=sensor_input_verified,session_policy=session_policy,max_actions=max_actions,action_history_limit=action_history_limit)
  from runtime_device import cursor_preferences
  self.gyro_enabled=cursor_preferences()[0]
  self.router=AdaptivePrefixRouter(self._emit,clock=clock,motion_enabled=sensor_input_verified and self.gyro_enabled,session_policy=session_policy,max_actions=max_actions,session_bounded_hold=True)
  self.prefix_sensor_verified=sensor_input_verified
  self.router.on_pointer_resume=self._center_pointer
 def _center_pointer(self):
  # Only an absolute-coordinate output can place the cursor; relative-only
  # hardware keeps wherever the TV has it.
  center=getattr(self.outputs,'center_pointer',None)
  if center is not None and self.bridge.sensor_input_verified:center()
 def feed_raw(self,generation,report):
  if self.closed or self.failed or generation != self.generation or self.generation is None:return False
  try:
   self.router.motion_enabled=self.bridge.sensor_input_verified and self.gyro_enabled
   return self.router.feed(generation,report)
  except BaseException:
   self.failed=True;self._stop_after_error();raise
 def summary(self):
  result=super().summary()
  result['bridge']['prefixRoutingUsed']=True
  result['bridge']['legacyDemuxCountsApplicable']=False
  result['candidatePhysicalAxesValidated']=False
  return result
 def tick(self):
  if self.closed:raise RuntimeError('receiver-closed')
  try:
   delta=self.router.tick()
   if self.bridge.sensor_input_verified:self._move(delta)
  except BaseException:
   self.failed=True;self._stop_after_error();raise
