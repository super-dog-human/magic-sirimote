"""Pure swipe-direction recognizer for the requested swipe-and-click policy.

One validated cardinal swipe emits one of up/down/left/right. This helper
does not open devices or inject keys. In the requested interaction, a
physical surface press anywhere is handled separately by TouchClick; the
native adapter must verify its exact key/click output devices and their
permissions.
"""
import math
import time
from touch_coordinates import decode_touch


class TouchDpad:
    THRESHOLD = 180
    DOMINANCE = 1.4
    MAX_SAMPLE_JUMP = 300
    IDLE_SECONDS = .5

    def __init__(self, emit, *, clock=time.monotonic, max_seconds=30, max_steps=16):
        if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 60:
            raise ValueError('Finite session, at most 60 seconds')
        if type(max_steps) is not int or not 1 <= max_steps <= 16:
            raise ValueError('At most sixteen semantic direction steps')
        self.emit, self.clock = emit, clock
        self.max_seconds, self.max_steps = max_seconds, max_steps
        self.born = self.last_time = clock()
        if not math.isfinite(self.born):raise ValueError('Finite monotonic clock')
        self.generation, self.highest = None, 0
        self.closed, self.reason = False, None
        self.counts = dict.fromkeys(('up','down','left','right'),0)
        self._reset()

    def _reset(self):
        self.origin = self.previous = self.last_input = None
        self.fired = False

    def stop(self, reason='requested'):
        if not self.closed:
            self.closed, self.reason, self.generation = True, reason, None
            self._reset()

    def _now(self):
        if self.closed:return None
        now = self.clock()
        if not math.isfinite(now) or now < self.last_time:
            self.stop('clock-invalid');return None
        self.last_time = now
        if now-self.born >= self.max_seconds:
            self.stop('deadline');return None
        return now

    def bind(self, generation):
        if type(generation) is not int or generation <= self.highest:raise ValueError('Fresh link generation')
        if self._now() is None:return False
        if self.generation is not None:raise RuntimeError('Unbind previous link first')
        self.generation = self.highest = generation
        self._reset();return True

    def unbind(self, generation):
        if type(generation) is not int or generation != self.generation:return False
        self.generation = None;self._reset();return True

    def tick(self):
        now = self._now()
        if now is not None and self.last_input is not None and now-self.last_input >= self.IDLE_SECONDS:
            self._reset()

    def feed(self, generation, value):
        now = self._now()
        if now is None or type(generation) is not int or self.generation is None or generation != self.generation:return None
        if self.last_input is not None and now-self.last_input >= self.IDLE_SECONDS:self._reset()
        d = decode_touch(value)
        if d is None or len(d['fingers']) != 1 or d['buttons']:
            self._reset();return None
        f = d['fingers'][0]
        if f['state'] not in (3,4):
            self._reset();return None
        current = (f['x'],f['y'],d['clock'])
        self.last_input = now
        if self.origin is None:
            # A contact already held at startup/reconnect cannot become a swipe.
            if f['state'] == 3:self.origin = self.previous = current
            return None
        ticks = (current[2]-self.previous[2]) & 65535
        if ticks == 0:return None
        if ticks > 200 or max(abs(current[i]-self.previous[i]) for i in (0,1)) > self.MAX_SAMPLE_JUMP:
            self._reset();return None
        self.previous = current
        if self.fired:return None
        x,y = current[0]-self.origin[0],current[1]-self.origin[1]
        if max(abs(x),abs(y)) < self.THRESHOLD:return None
        if abs(x) >= self.DOMINANCE*abs(y):direction = 'right' if x>0 else 'left'
        elif abs(y) >= self.DOMINANCE*abs(x):direction = 'up' if y>0 else 'down'
        else:return None
        if sum(self.counts.values()) >= self.max_steps:
            self.stop('step-budget');return None
        self.fired = True
        try:self.emit(direction)
        except BaseException:
            self.stop('emit-failed-no-retry');raise
        self.counts[direction] += 1
        return direction

    def summary(self):
        return {'directions':dict(self.counts),'closed':self.closed,'reason':self.reason,
                'maxSeconds':self.max_seconds,'maxSteps':self.max_steps,
                'cursorEvents':0,'deviceOrNetworkOpens':0,'liveKeyWrites':0,
                'policy':'one direction per stroke; new contact after lift; physical click separate'}
