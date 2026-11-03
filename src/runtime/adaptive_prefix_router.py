"""Offline FC21 router. Pointer and semantic events are returned to fake sinks."""
from adaptive_prefix_pose import AdaptivePrefixPose
from runtime_device import cursor_preferences
from normalize import normalize
from position_press import SurfaceRegions
from swipe_click import SwipeClick
from navigation_mode import NavigationMode

class AdaptivePrefixRouter:
 def __init__(self, emit, *, clock, motion_enabled=True, session_policy=None, max_actions=12):
  if type(motion_enabled) is not bool:raise ValueError('explicit motion gate required')
  self.motion_enabled=motion_enabled;self.clock=clock;self.pose=AdaptivePrefixPose(sensitivity=cursor_preferences()[1]);self.generation=None;self.closed=False
  self.navigation=NavigationMode();self.emit=emit
  seconds=30. if session_policy is None else session_policy.seconds
  self.press=SwipeClick(self._semantic,SurfaceRegions(x_min=-1768,x_max=-200,y_min=-1032,y_max=440),clock=clock,max_seconds=seconds,max_actions=max_actions,session_policy=session_policy)
 def _semantic(self,action,down):
  if down and action in ('up','down','left','right'):
   self.navigation.select_navigation(self.clock());self.pose._clear_tracking()
  return self.emit(action,down)
 def bind(self,generation):
  if self.closed or self.generation is not None:return False
  if self.press.bind(generation):self.generation=generation;return True
  return False
 def feed(self,generation,frame):
  if self.closed or type(generation) is not int or generation != self.generation or self.generation is None:return False
  sample=normalize(frame)
  if sample is None:
   # Unknown input is not treated as an intentional finger lift.
   self.press.feed(generation,b'');self.navigation.observe(None,self.clock());self.pose.feed(None,self.clock());return False
  self.press.feed(generation,sample['touch_value'])
  if self.press.core.closed:self.pose.stop();return False
  now=self.clock()
  if self.navigation.observe(sample if self.motion_enabled else None,now):self.pose._clear_tracking()
  self.pose.feed(sample if self.motion_enabled else None,now)
  if self.navigation.mode=='navigation':self.pose._clear_tracking()
  return True
 def tick(self):
  if self.closed:return None
  self.press.tick()
  if self.press.core.closed:self.pose.stop();return None
  if self.navigation.mode=='navigation':return None
  return self.pose.tick(self.clock())
 def summary(self):
  return {'closed':self.closed,'activeGeneration':self.generation,'press':self.press.summary(),'pointer':self.pose.summary(),'navigation':self.navigation.summary(),'motionGateOpen':self.motion_enabled,'physicalAxesValidated':False,'candidateNotHardwareAccepted':True,'rawReportsPersisted':False}
 def stop(self, reason='offline-stop'):
  if self.closed:return
  self.closed=True
  try:self.press.stop(reason)
  finally:self.generation=None;self.pose.stop()
