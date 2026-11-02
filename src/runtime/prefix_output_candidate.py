"""Offline-only adapter to the existing verified-output boundary.

The caller must separately establish target and sensor authorization. The
flag is a synthetic-test gate, not proof that real FC21 data is orientation.
"""
from combined_receiver import CombinedReceiver
from adaptive_prefix_router import AdaptivePrefixRouter

class PrefixOutputCandidate(CombinedReceiver):
 def __init__(self,outputs,*,clock,sensor_input_verified=False,session_policy=None,max_actions=12,action_history_limit=None):
  if type(sensor_input_verified) is not bool:raise ValueError('explicit gate required')
  super().__init__(outputs,clock=clock,sensor_input_verified=sensor_input_verified,session_policy=session_policy,max_actions=max_actions,action_history_limit=action_history_limit)
  self.router=AdaptivePrefixRouter(self._emit,clock=clock,motion_enabled=sensor_input_verified,session_policy=session_policy,max_actions=max_actions)
  self.prefix_sensor_verified=sensor_input_verified
 def feed_raw(self,generation,report):
  if self.closed or self.failed or generation != self.generation or self.generation is None:return False
  try:
   self.router.motion_enabled=self.bridge.sensor_input_verified
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
