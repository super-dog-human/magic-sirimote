"""Persistent directional/pointer selection, with bounded motion activation.

No I/O. A direction selects navigation until a deliberate side-to-side shake.
Deliberate means the remote's horizontal heading (yaw) turns around at least
FOLD_COUNT times within FOLD_WINDOW seconds, each stroke being at least
STROKE_RADIANS wide. A stroke only counts when it is mainly horizontal: its
vertical travel may not exceed MAX_VERTICAL_RATIO of its horizontal travel, so
shaking up and down does nothing even if the wrist twists a little sideways.
Slow drift and the small wobble between consecutive swipes stay in navigation.
The owning continuous receiver preserves this state across segment rollover.
"""
import math
from collections import deque
from pose_math import compact_quaternion, pointing_angles, shortest_angle

_IDENTITY=(0.,0.,0.,1.)

class NavigationMode:
 # A stroke must travel at least this far (rad, about 5.7 degrees) before the
 # next stroke in the opposite direction counts as a turnaround.
 STROKE_RADIANS=.10
 # This many turnarounds ...
 FOLD_COUNT=2
 # ... with no more than this much time between the first and the last one.
 FOLD_WINDOW=.5
 # A stroke counts only if its vertical travel is at most this share of its horizontal travel.
 MAX_VERTICAL_RATIO=.6
 RELEASE_DELAY=.35
 MAX_GAP=.06
 MAX_REPORT_STEP=1.0
 def __init__(self):
  self.mode='pointer';self.direction_switches=0;self.pointer_switches=0
  self.blocked_until=0.;self.turns=deque();self._clear()
 def _clear(self):
  self.previous=None;self.previous_at=None;self.raw_yaw=None;self.yaw=0.
  self.anchor=None;self.direction=0;self.extreme=0.;self.extreme_at=0.;self.turns.clear()
  self.stroke_start=0.;self.pitch_range=None;self.extreme_pitch_range=None
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
  # Horizontal heading of the pointing ray. Undefined near straight up/down.
  heading=pointing_angles(_IDENTITY,q)
  if heading is None:self._clear();return False
  if self.raw_yaw is None:self.yaw=0.
  else:self.yaw+=shortest_angle(heading[0]-self.raw_yaw)
  self.raw_yaw=heading[0]
  return self._track_turns(now,heading[1])
 def _track_turns(self,now,pitch):
  y=self.yaw
  low,high=self.pitch_range if self.pitch_range is not None else (pitch,pitch)
  self.pitch_range=(min(low,pitch),max(high,pitch))
  if self.direction==0:
   # No stroke yet: wait for the first one to travel far enough.
   if self.anchor is None:self.anchor=self.stroke_start=y;self.pitch_range=(pitch,pitch)
   elif abs(y-self.anchor)>=self.STROKE_RADIANS:
    self.direction=1 if y>self.anchor else -1;self.extreme=y;self.extreme_at=now
    self.extreme_pitch_range=self.pitch_range
   return False
  if (y-self.extreme)*self.direction>=0:
   self.extreme=y;self.extreme_at=now;self.extreme_pitch_range=self.pitch_range;return False
  if (self.extreme-y)*self.direction<self.STROKE_RADIANS:return False
  # The stroke reversed by a full stroke width: a turnaround at the extreme.
  # Only a mainly horizontal stroke counts (horizontal travel shrinks with elevation).
  vertical=self.extreme_pitch_range[1]-self.extreme_pitch_range[0]
  horizontal=abs(self.extreme-self.stroke_start)*math.cos(max(abs(p) for p in self.extreme_pitch_range))
  if vertical<=self.MAX_VERTICAL_RATIO*horizontal:self.turns.append(self.extreme_at)
  else:self.turns.clear()
  self.direction=-self.direction;self.stroke_start=self.extreme;self.extreme=y;self.extreme_at=now
  self.pitch_range=self.extreme_pitch_range=(pitch,pitch)
  while len(self.turns)>1 and self.turns[-1]-self.turns[0]>self.FOLD_WINDOW:self.turns.popleft()
  if len(self.turns)<self.FOLD_COUNT:return False
  self.mode='pointer';self.pointer_switches+=1;self._clear();return True
 def summary(self):
  return {'mode':self.mode,'directionSwitches':self.direction_switches,'pointerSwitches':self.pointer_switches}
