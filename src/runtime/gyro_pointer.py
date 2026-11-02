"""Offline, bounded body-rate pointer candidate; no real input or device I/O.

Main0241 compact vector B follows the firmware's previous gyro sample minus
estimated bias, scaled by1000. Axes/signs are explicit trial parameters, NOT
certified physical screen mappings. Host interarrival time is not a sensor
timestamp. A live adapter must independently authenticate target/link/handle,
keep tick running, and enforce its own device/write/visibility safeguards.
"""
import math
import time
from motion_report import decode_compact_motion


class GyroPointer:
    CALIBRATION_SECONDS = 2.
    MIN_CALIBRATION_SAMPLES = 75
    MAX_GAP = .06
    MAX_STEP = 8
    MAX_RATE = 2.
    STATIONARY_LIMIT = .08
    MIN_DEADZONE = .006
    MAX_DEADZONE = .03
    RELEASE_PAUSE = .1

    def __init__(self, *, axes, signs, gain=400., max_seconds=30., clock=time.monotonic, calibration_batch_tolerant=False, session_policy=None):
        if type(calibration_batch_tolerant) is not bool:
            raise ValueError('Explicit calibration batch policy required')
        self.calibration_batch_tolerant=calibration_batch_tolerant
        if type(axes) is not tuple or len(axes) != 2 or any(type(x) is not int or x not in (0,1,2) for x in axes) or axes[0] == axes[1]:
            raise ValueError('Explicit distinct body-rate axes required')
        if type(signs) is not tuple or len(signs) != 2 or any(type(x) is not int or x not in (-1,1) for x in signs):
            raise ValueError('Explicit provisional signs required')
        if type(gain) not in (int,float) or not math.isfinite(gain) or not 10 <= gain <= 500:
            raise ValueError('Finite gain10..500 pixels/radian required')
        from input_session_policy import resolve_session_bounds
        max_seconds, _ = resolve_session_bounds(max_seconds, session_policy)
        self.axes, self.signs, self.gain = axes, signs, gain
        self.clock, self.max_seconds = clock, max_seconds
        self.started = self.last_clock = clock()
        if type(self.started) not in (int,float) or not math.isfinite(self.started):
            raise ValueError('Finite clock required')
        self.generation, self.highest_generation = None, 0
        self.closed, self.reason = False, None
        self.last_calibration = None
        self.counts = dict.fromkeys(('validFrames','discardedFrames','motionFrames','clampedFrames',
                                    'calibrationResets','pressSuppressed','staleFrames','calibrationBatchedSkipped'), 0)
        self.reset_reasons=dict.fromkeys(('silence','malformed','timing','buttons','touch-or-motion','noise','unspecified'),0)
        self._reset()

    def _reset(self):
        self.previous = self.calibration_start = None
        self.n = 0
        self.mean, self.m2 = [0.]*3, [0.]*3
        self.bias = self.deadzones = None
        self.carry = [0.,0.]
        self.pause_until = 0.
        self.travel = []

    def _now(self):
        if self.closed:
            return None
        now = self.clock()
        if type(now) not in (int,float) or not math.isfinite(now) or now < self.last_clock:
            self.stop('invalid-clock'); return None
        self.last_clock = now
        if now-self.started >= self.max_seconds:
            self.stop('deadline'); return None
        return now

    def bind(self, generation):
        if type(generation) is not int or generation <= self.highest_generation:
            raise ValueError('Fresh positive generation required')
        if self.generation is not None:
            raise RuntimeError('Unbind old link first')
        if self._now() is None:
            return False
        self._reset()
        self.last_calibration = None
        self.generation = self.highest_generation = generation
        return True

    def unbind(self, generation):
        if type(generation) is int and generation == self.generation:
            self.generation = None; self._reset(); return True
        return False

    def stop(self, reason='requested'):
        if not self.closed:
            self.closed, self.reason, self.generation = True, reason, None
            self._reset()

    def tick(self):
        now = self._now()
        if now is not None and self.previous is not None and now-self.previous > self.MAX_GAP:
            self.previous = None
            self.carry = [0.,0.]
            if self.bias is None:
                self._reset_calibration('silence')

    def _reset_calibration(self,reason='unspecified'):
        self.calibration_start, self.n = None, 0
        self.mean, self.m2 = [0.]*3, [0.]*3
        self.counts['calibrationResets'] += 1
        self.reset_reasons[reason] += 1

    def feed(self, generation, value):
        now = self._now()
        if now is None:
            return None
        if type(generation) is not int or generation != self.generation or self.generation is None:
            self.counts['staleFrames'] += 1; return None
        sample = decode_compact_motion(value)
        if sample is None:
            self.previous = None; self.carry = [0.,0.]
            if self.bias is None: self._reset_calibration('malformed')
            self.counts['discardedFrames'] += 1; return None
        touch = sample['touch']
        rate = [n/1000. for n in sample['scaledVectorB']]
        prior, self.previous = self.previous, now
        dt = None if prior is None else now-prior
        # Reject batched/late reports; never integrate across a gap or replay.
        if dt is not None and not .005 <= dt <= self.MAX_GAP:
            self.carry = [0.,0.]
            if self.bias is None:
                if self.calibration_batch_tolerant and 0<=dt<.005:
                    # A batched arrival is neither an independent calibration
                    # sample nor evidence that the body moved. Skip it without
                    # weighting it or restarting a still-valid static window.
                    self.counts['calibrationBatchedSkipped'] += 1
                else:self._reset_calibration('timing')
            self.counts['discardedFrames'] += 1; return None
        self.counts['validFrames'] += 1
        blocked = bool(sample['buttons']) or (touch is not None and len(touch['fingers']) != 1)
        if blocked:
            self.pause_until = now+self.RELEASE_PAUSE
            self.carry = [0.,0.]
            if self.bias is None: self._reset_calibration('buttons')
            self.counts['pressSuppressed'] += 1; return None
        if now < self.pause_until:
            self.carry = [0.,0.]; return None
        if self.bias is None:
            # Calibration is stillness-only; never learn a deliberate slow turn
            # above the bounded threshold or learn while fingers rest on pad.
            if touch is not None or max(abs(x) for x in rate) > self.STATIONARY_LIMIT:
                self._reset_calibration('touch-or-motion'); return None
            if self.calibration_start is None:
                self.calibration_start = now
            self.n += 1
            for i, x in enumerate(rate):
                delta = x-self.mean[i]
                self.mean[i] += delta/self.n
                self.m2[i] += delta*(x-self.mean[i])
            if now-self.calibration_start >= self.CALIBRATION_SECONDS and self.n >= self.MIN_CALIBRATION_SAMPLES:
                zones = [max(self.MIN_DEADZONE, 6*math.sqrt(max(0., x)/self.n)) for x in self.m2]
                if max(zones) > self.MAX_DEADZONE:
                    self._reset_calibration('noise'); return None
                self.bias, self.deadzones = tuple(self.mean), tuple(zones)
                self.last_calibration = {'atMs': round((now-self.started)*1000),
                                         'samples': self.n, 'bias': self.bias,
                                         'deadzones': self.deadzones}
            return None
        if dt is None:
            self.carry = [0.,0.]; return None
        corrected = [x-b for x,b in zip(rate, self.bias)]
        if max(abs(x) for x in corrected) > self.MAX_RATE:
            self.carry = [0.,0.]
            self.counts['discardedFrames'] += 1; return None
        delta = []
        clamped = False
        for out, (axis, sign) in enumerate(zip(self.axes, self.signs)):
            speed = corrected[axis]
            if abs(speed) <= self.deadzones[axis]:
                self.carry[out] = 0.; delta.append(0); continue
            # Continuous dead-zone edge, not a jump in velocity at threshold.
            speed -= math.copysign(self.deadzones[axis], speed)
            raw = sign*speed*dt*self.gain + self.carry[out]
            limited = max(-self.MAX_STEP, min(self.MAX_STEP, raw))
            clamped |= limited != raw
            integer = math.trunc(limited)
            self.carry[out] = limited-integer
            delta.append(integer)
        if delta == [0,0]:
            return None
        self.travel = [(t,d) for t,d in self.travel if t > now-1]
        distance = sum(abs(x) for x in delta)
        if len(self.travel) >= 60 or sum(d for _,d in self.travel)+distance > 600:
            self.carry = [0.,0.]
            self.counts['discardedFrames'] += 1; return None
        self.travel.append((now,distance))
        self.counts['motionFrames'] += 1
        self.counts['clampedFrames'] += int(clamped)
        return tuple(delta)

    def summary(self):
        return {**self.counts, 'calibrated': self.bias is not None, 'bias': self.bias,
                'calibrationResult': self.last_calibration,
                'deadzones': self.deadzones, 'closed': self.closed, 'reason': self.reason,
                'axes': self.axes, 'signs': self.signs, 'gain': self.gain,
                'physicalScreenMappingValidated': False, 'nativeInputWrites': 0,
                'calibrationResetReasons':dict(self.reset_reasons),
                'calibrationBatchTolerant':self.calibration_batch_tolerant,
                'deviceOrNetworkOpens': 0, 'automaticRetries': 0}
