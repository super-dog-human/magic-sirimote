"""Offline-only FC21 pose experiment using the existing gain-85 filter.

Calibrates from orientation stability, not the missing angular-rate fields.
All axes, stillness thresholds and the device's truncated data remain unproven.
No device, Bluetooth or native input operations are performed here.
"""
import math
from pose_math import compact_quaternion, conjugate, pointing_angles, shortest_angle
from vector_adaptive_pose_pointer import ReducedGainVectorAdaptivePosePointer


class AdaptivePrefixPose:
    CALIBRATION_SECONDS = 1.0
    CALIBRATION_SAMPLES = 20
    STATIONARY_RADIANS = .025
    MAX_GAP = .06
    PERIOD = .020
    ANGLE_DEADBAND = .00035
    MAX_SINGLE_REPORT_ROTATION = 1.0
    AXIS_GAINS = (3230., 4845.)
    # Reuse the existing shared-vector filter, not fabricated sensor rates.
    _alpha = staticmethod(ReducedGainVectorAdaptivePosePointer._alpha)
    MIN_CUTOFF_HZ = ReducedGainVectorAdaptivePosePointer.MIN_CUTOFF_HZ
    BETA = ReducedGainVectorAdaptivePosePointer.BETA
    DERIVATIVE_CUTOFF_HZ = ReducedGainVectorAdaptivePosePointer.DERIVATIVE_CUTOFF_HZ
    _render_target = ReducedGainVectorAdaptivePosePointer._render_target

    def __init__(self):
        self.last_time = None
        self.reference_inverse = None
        self.origin = self.epoch = None
        self.samples = 0
        self.closed = False
        self.stats = dict.fromkeys(('reports','validPose','blocked','calibrationResets','jumps','geometryRejected','renderTicks','motionFrames','gaps'), 0)
        self._clear_tracking()

    def _clear_tracking(self):
        self.previous = self.last_pose = self.pending = self.previous_q = None
        self.output_angles = self.render_at = self.next_tick_at = None
        self.unwrapped = [0., 0.]
        self._adaptive_previous_raw = self._adaptive_filtered = self._adaptive_derivative = None

    def _reset_calibration(self):
        self.origin = self.epoch = None
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
            if self.origin is None:
                self.origin, self.epoch, self.samples = q, now, 1
                return
            angular_change = 2 * math.acos(min(1., abs(sum(a*b for a, b in zip(self.origin, q)))))
            if angular_change > self.STATIONARY_RADIANS:
                self.stats['calibrationResets'] += 1
                self.origin, self.epoch, self.samples = q, now, 1
                return
            self.samples += 1
            if now - self.epoch >= self.CALIBRATION_SECONDS and self.samples >= self.CALIBRATION_SAMPLES:
                self.reference_inverse = conjugate(q)
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

    def summary(self):
        return {**self.stats, 'calibrated': self.reference_inverse is not None, 'physicalAxesValidated': False, 'rawReportsPersisted': False}

    def stop(self):
        self.closed = True
        self._clear_tracking()
