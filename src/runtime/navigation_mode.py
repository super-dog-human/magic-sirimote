"""Persistent directional/pointer selection, with bounded motion activation.

No I/O. A direction selects navigation until a deliberate untouching movement.
The owning continuous receiver preserves this state across segment rollover.
"""
import math
from pose_math import compact_quaternion

class NavigationMode:
 ACTIVATION_RADIANS=.32
 WINDOW_SECONDS=.70
 RELEASE_DELAY=.35
 MAX_GAP=.06
 MAX_REPORT_STEP=1.0
 def __init__(self):
  self.mode='pointer';self.direction_switches=0;self.pointer_switches=0
  self.blocked_until=0.;self.anchor=self.previous=None;self.anchor_at=self.previous_at=None
 def _clear(self):
  self.anchor=self.previous=None;self.anchor_at=self.previous_at=None
 def select_navigation(self,now):
  if self.mode!='navigation':self.direction_switches+=1
  self.mode='navigation';self.blocked_until=now+self.RELEASE_DELAY;self._clear()
 def observe(self,sample,now):
  if self.mode=='pointer':return False
  valid=(type(sample) is dict and sample.get('touch_active') is False and
         sample.get('touch_value')==b'\x00\x00' and sample.get('orientation3') is not None)
  if not valid:
   self.blocked_until=now+self.RELEASE_DELAY;self._clear();return False
  if now<self.blocked_until:self._clear();return False
  q=compact_quaternion(sample['orientation3'])
  if q is None:self._clear();return False
  def angle(a,b):return 2*math.acos(min(1.,abs(sum(x*y for x,y in zip(a,b)))))
  if (self.previous_at is not None and
      (now<self.previous_at or now-self.previous_at>self.MAX_GAP or angle(q,self.previous)>self.MAX_REPORT_STEP)):
   self._clear()
  self.previous,self.previous_at=q,now
  if self.anchor is None or now-self.anchor_at>self.WINDOW_SECONDS:
   self.anchor,self.anchor_at=q,now;return False
  if angle(q,self.anchor)<self.ACTIVATION_RADIANS:return False
  self.mode='pointer';self.pointer_switches+=1;self._clear();return True
 def summary(self):
  return {'mode':self.mode,'directionSwitches':self.direction_switches,'pointerSwitches':self.pointer_switches}
