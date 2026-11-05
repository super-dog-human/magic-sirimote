"""FC21 pose tracking with adaptive filtering and selectable sensitivity.

Initializes from a short continuous pose stream, without waiting for
stillness. Touch-bearing prefixes do not contain a complete orientation. No
device, Bluetooth or native input operations are performed here.
"""
import math
from pose_math import compact_quaternion, heading_reference_inverse, pointing_angles, shortest_angle
from vector_adaptive_pose_pointer import ReducedGainVectorAdaptivePosePointer


class AdaptivePrefixPose:
    CALIBRATION_SECONDS = .15
    CALIBRATION_SAMPLES = 8
    STARTUP_MAX_REPORT_ROTATION = .20
    MAX_GAP = .06
    PERIOD = .020
    ANGLE_DEADBAND = .00035
    MAX_SINGLE_REPORT_ROTATION = 1.0
    AXIS_GAINS = (1453.5, 1453.5)
    SENSITIVITY_FACTORS = (.25, .5, .75, 1., 1.25)
    # Resting-pose noise must not accumulate into visible cursor creep.
    REST_RADIUS = .0012
    REST_SECONDS = .20
    RESUME_RADIUS = .0025
    REST_TRACK_SECONDS = 1.0
    # Reuse the existing shared-vector filter, not fabricated sensor rates.
    _alpha = staticmethod(ReducedGainVectorAdaptivePosePointer._alpha)
    MIN_CUTOFF_HZ = ReducedGainVectorAdaptivePosePointer.MIN_CUTOFF_HZ
    BETA = ReducedGainVectorAdaptivePosePointer.BETA
    DERIVATIVE_CUTOFF_HZ = ReducedGainVectorAdaptivePosePointer.DERIVATIVE_CUTOFF_HZ
    _render_target = ReducedGainVectorAdaptivePosePointer._render_target

    def __init__(self, sensitivity=3):
        if type(sensitivity) is not int or not 1 <= sensitivity <= 5:
            raise ValueError('Choose sensitivity 1..5')
        self.AXIS_GAINS = tuple(g * self.SENSITIVITY_FACTORS[sensitivity - 1] for g in type(self).AXIS_GAINS)
        self.last_time = None
        self.reference_inverse = None
        self._reset_calibration()
        self.closed = False
        self.stats = dict.fromkeys(('reports','validPose','blocked','calibrationResets','jumps','geometryRejected','renderTicks','motionFrames','gaps'), 0)
        self._clear_tracking()

    def _clear_tracking(self):
        self.previous = self.last_pose = self.pending = self.previous_q = None
        self.output_angles = self.render_at = self.next_tick_at = None
        self.unwrapped = [0., 0.]
        self.rest_anchor = self.rest_since = None
        self.resting = True
        self._adaptive_previous_raw = self._adaptive_filtered = self._adaptive_derivative = None

    def _reset_calibration(self):
        self.origin = self.epoch = self.initial_at = None
        self.samples = 0

    def _time(self, now):
        if self.closed:
            return False
        if type(now) not in (int, float) or not math.isfinite(now) or (self.last_time is not None and now < self.last_time):
            self.closed = True
            self._clear_tracking()
            return False
        self.last_time = now
        return True

    def feed(self, sample, now):
        if not self._time(now):
            return
        self.stats['reports'] += 1
        if self.previous is not None and now - self.previous > self.MAX_GAP:
            self.stats['gaps'] += 1
            self._clear_tracking()
            if self.reference_inverse is None:
                self._reset_calibration()
        if (type(sample) is not dict or sample.get('touch_active') is not False or
            sample.get('orientation3') is None or type(sample.get('touch_value')) is not bytes or
            len(sample['touch_value']) != 2 or sample['touch_value'][0] != 0 or sample['touch_value'][1] != 0):
            self.stats['blocked'] += 1
            self._clear_tracking()
            if self.reference_inverse is None:
                self._reset_calibration()
            return
        q = compact_quaternion(sample['orientation3'])
        if q is None:
            self._clear_tracking()
            if self.reference_inverse is None:
                self._reset_calibration()
            return
        self.stats['validPose'] += 1
        self.previous = now
        if self.reference_inverse is None:
            # A baseline is a coordinate reference, not a stationary bias estimate.
            # Check continuity and adjacent-sample plausibility while allowing
            # normal movement. Discard all warm-up displacement at acceptance.
            if self.origin is not None:
                step = 2 * math.acos(min(1., abs(sum(a*b for a, b in zip(self.origin, q)))))
                if now - self.initial_at > self.MAX_GAP or step > self.STARTUP_MAX_REPORT_ROTATION:
                    self.stats['calibrationResets'] += 1
                    self._reset_calibration()
            if self.epoch is None:
                self.epoch = now
            self.origin, self.initial_at = q, now
            self.samples += 1
            if now - self.epoch >= self.CALIBRATION_SECONDS and self.samples >= self.CALIBRATION_SAMPLES:
                self.reference_inverse = heading_reference_inverse(q)
                if self.reference_inverse is None:
                    self.stats['geometryRejected'] += 1
                    return
                self._reset_calibration()
                self._clear_tracking()
            return
        if self.previous_q is not None:
            jump = 2 * math.acos(min(1., abs(sum(a*b for a, b in zip(self.previous_q, q)))))
            if jump > self.MAX_SINGLE_REPORT_ROTATION:
                self.stats['jumps'] += 1
                self._clear_tracking()
                return
        self.previous_q = q
        angles = pointing_angles(self.reference_inverse, q)
        if angles is None:
            self.stats['geometryRejected'] += 1
            self._clear_tracking()
            return
        if self.last_pose is None:
            self.unwrapped = list(angles)
            self.output_angles = list(angles)
            self.render_at, self.next_tick_at = now, now + self.PERIOD
        else:
            self.unwrapped[0] += shortest_angle(angles[0] - self.last_pose[0])
            self.unwrapped[1] += angles[1] - self.last_pose[1]
        self.last_pose = angles
        self.pending = (now, tuple(self.unwrapped))

    def tick(self, now):
        if not self._time(now):
            return None
        if self.previous is None or now - self.previous > self.MAX_GAP:
            self._clear_tracking()
            if self.reference_inverse is None:
                self._reset_calibration()
            return None
        if self.pending is None or self.next_tick_at is None or now < self.next_tick_at - 1e-9:
            return None
        stamp, target = self.pending
        self.pending = None
        if now - stamp > self.MAX_GAP or now - self.render_at > self.MAX_GAP:
            self._clear_tracking()
            return None
        elapsed = now - self.render_at
        if elapsed <= 0:
            self._clear_tracking()
            return None
        self.render_at, self.next_tick_at = now, now + self.PERIOD
        filtered = self._render_target(target, elapsed)
        if self._hold_resting_noise(filtered, now, elapsed):
            self.output_angles = list(filtered)
            self.stats['renderTicks'] += 1
            return None
        result = []
        for axis, gain in enumerate(self.AXIS_GAINS):
            difference = filtered[axis] - self.output_angles[axis]
            n = 0 if abs(difference) < self.ANGLE_DEADBAND else math.trunc(difference * gain)
            self.output_angles[axis] += n / gain
            result.append(n)
        self.stats['renderTicks'] += 1
        if result != [0, 0]:
            self.stats['motionFrames'] += 1
            return tuple(result)
        return None

    def _hold_resting_noise(self, target, now, elapsed):
        if self.rest_anchor is None:
            self.rest_anchor = list(target)
            self.rest_since = now
        distance = math.hypot(*(target[i] - self.rest_anchor[i] for i in range(2)))
        if self.resting:
            if distance <= self.RESUME_RADIUS:
                # Follow very slow sensor drift while resting, but retain a
                # threshold for deliberate movement. Never replay held motion.
                alpha = 1. - math.exp(-elapsed / self.REST_TRACK_SECONDS)
                self.rest_anchor = [a + alpha * (b-a) for a,b in zip(self.rest_anchor,target)]
                return True
            self.resting = False
            self.rest_anchor = list(target)
            self.rest_since = now
            return True  # Rebase at departure; do not jump over the dead zone.
        if distance > self.REST_RADIUS:
            self.rest_anchor = list(target)
            self.rest_since = now
        elif now - self.rest_since >= self.REST_SECONDS:
            self.resting = True
            self.rest_anchor = list(target)
            return True
        return False

    def summary(self):
        return {**self.stats, 'calibrated': self.reference_inverse is not None, 'physicalAxesValidated': False, 'rawReportsPersisted': False}

    def stop(self):
        self.closed = True
        self._clear_tracking()
