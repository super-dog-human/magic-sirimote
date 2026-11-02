"""FC hidraw bridge to the existing bounded touch/gyro input router.

Sensor-derived compact motion is blocked by default because the CCCD-to-hidraw
sensor path is not verified. No code here activates/disables sensors or performs
I/O. Touch-only reports continue through the existing swipe-click policy.
"""
from collections import Counter

from hidraw_frame_demux import (
    demux_report, MOTION_REPORT_LENGTHS,
)
from input_router import InputRouter
from vector_adaptive_pose_pointer import ReducedGainVectorAdaptivePosePointer

SENSOR_INPUT_UNVERIFIED = True


class GatedHidrawRouter:
    def __init__(self, router, *, sensor_input_verified=False, session_policy=None):
        if type(sensor_input_verified) is not bool:
            raise ValueError('exact motion verification flag required')
        if type(router) is not InputRouter:
            raise ValueError('exact reviewed InputRouter required')
        from input_session_policy import InputSessionPolicy
        if session_policy is not None and type(session_policy) is not InputSessionPolicy:
            raise ValueError('exact sustained policy required')
        expected_seconds = 30. if session_policy is None else session_policy.seconds
        expected_actions = 16 if session_policy is None else session_policy.max_actions
        if (router.touch_mode != 'swipe-click'
                or type(router.pointer) is not ReducedGainVectorAdaptivePosePointer
                or tuple(router.pointer.AXIS_GAINS) != (3400., 5100.)
                or router.pointer.max_seconds != expected_seconds
                or router.press.core.max_seconds != expected_seconds
                or router.press.max_actions != expected_actions):
            raise ValueError('accepted gain85/swipe-click profile and matching session limits required')
        self.router = router
        self.sensor_input_verified = sensor_input_verified
        self.counts = Counter()
        self.closed = False
        self.reason = None

    def feed_read(self, generation, report):
        """Process one complete hidraw read; never assemble or split reports."""
        if self.closed:
            return None
        try:
            payload = demux_report(report)
        except BaseException:
            self.closed = True
            self.reason = 'demux-exception'
            self.counts['demuxErrors'] += 1
            raise
        if payload is None:
            self.counts['rejected'] += 1
            return None
        if len(report) in MOTION_REPORT_LENGTHS:
            if not self.sensor_input_verified:
                self.counts['motionBlockedUnverified'] += 1
                return None
            route_kind = 'motion'
        else:
            route_kind = 'touch'
        is_current_generation = (type(generation) is int
                                 and generation == self.router.generation
                                 and self.router.generation is not None)
        if not is_current_generation:
            self.counts['staleGenerationReports'] += 1
        try:
            self.router.feed(generation, payload)
            result = self.router.tick()
        except BaseException:
            self.closed = True
            self.reason = 'router-exception'
            self.counts['routerErrors'] += 1
            raise
        self.counts['routerCalls'] += 1
        if is_current_generation:
            self.counts[f'{route_kind}ForwardedForCurrentGeneration'] += 1
        return result

    def summary(self):
        return {
            'sensorInputUnverified': SENSOR_INPUT_UNVERIFIED,
            'motionGateOpen': self.sensor_input_verified,
            'counts': dict(sorted(self.counts.items())),
            'closed': self.closed,
            'reason': self.reason,
            'rawReportsStored': False,
            'sensorCommands': 0,
            'deviceOrNetworkOpens': 0,
        }
