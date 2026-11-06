"""Conservative media-state selection for play/pause.

Only the coarse state and monotonic timestamp are retained. An unavailable,
ambiguous or old reply cannot justify a play or pause key.
"""
import math
import threading
import time


class PlaybackSnapshot:
 def __init__(self, *, clock=time.monotonic, max_age=2.0):
  if not callable(clock) or not isinstance(max_age,(int,float)) or isinstance(max_age,bool) or not math.isfinite(max_age) or max_age<=0:
   raise ValueError('invalid clock or age')
  self.clock=clock;self.max_age=max_age;self._lock=threading.Lock();self._state=None;self._time=None;self._version=0;self._expected=None

 def ticket(self):
  with self._lock:return self._version

 def update(self,reply,*,ticket=None):
  state=None
  if type(reply) is dict and reply.get('returnValue') is True:
   entries=reply.get('foregroundAppInfo')
   if type(entries) is list and len(entries)==1 and type(entries[0]) is dict:
    candidate=entries[0].get('playState')
    if candidate in ('playing','paused'):state=candidate
  now=self.clock()
  if type(now) not in (int,float) or not math.isfinite(now):state=None;now=None
  with self._lock:
   if ticket is not None and ticket!=self._version:return False
   # After a toggle, old or missing state does not establish completion. Wait
   # for the opposite state; otherwise a rapid second press could repeat it.
   if self._expected is not None:
    if state!=self._expected:self._state=None;self._time=None;return False
    self._expected=None
   self._state=state;self._time=now;return True

 def choose(self):
  now=self.clock()
  with self._lock:state,when=self._state,self._time
  if type(now) not in (int,float) or not math.isfinite(now) or when is None or not 0<=now-when<=self.max_age:return None
  return {'playing':'pause','paused':'play'}.get(state)

 def consume(self):
  now=self.clock()
  with self._lock:
   if type(now) not in (int,float) or not math.isfinite(now) or self._time is None or not 0<=now-self._time<=self.max_age:return None
   result={'playing':'pause','paused':'play'}.get(self._state)
   if result is not None:
    self._expected={'playing':'paused','paused':'playing'}[self._state]
    self._state=None;self._time=None;self._version+=1
   return result

 def cancel_consumed(self,ticket):
  # A skipped native dispatch must not wait forever for a playback change
  # that we never requested. Require a fresh status sample; never replay it.
  with self._lock:
   if ticket!=self._version:return False
   self._expected=None;self._state=None;self._time=None;self._version+=1
   return True


class MediaAwareSink:
 def __init__(self,sink,snapshot):
  if not callable(getattr(sink,'pulse',None)) or not all(callable(getattr(snapshot,n,None)) for n in ('consume','ticket','cancel_consumed')):raise ValueError('invalid sink')
  self.sink=sink;self.snapshot=snapshot;self.skipped=0
 def ready(self,action):
  # Readiness never consumes playback state or sends a key.
  return action!='playpause' or self.snapshot.choose() is not None
 def pulse(self,action):
  toggle=action=='playpause';ticket=None
  if toggle:
   action=self.snapshot.consume()
   if action is None:self.skipped+=1;return False
   ticket=self.snapshot.ticket()
  if self.sink.pulse(action) is False:
   if toggle:self.snapshot.cancel_consumed(ticket)
   self.skipped+=1;return False
  return True
