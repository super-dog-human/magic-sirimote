"""Bounded router for fused-pose motion and explicit touch policies.
"""
import math
import time

from direct_pose_pointer import DirectPosePointer
from motion_report import decode_compact_motion
from position_press import PositionPress, SurfaceRegions
from touch_coordinates import decode_touch


class InputRouter:
    """No native I/O. Emits semantic press actions through an injected sink."""
    def __init__(self, emit, *, clock=time.monotonic, max_seconds=30., pose_mode='direct',
                 touch_mode='press-position', session_policy=None):
        from input_session_policy import resolve_session_bounds
        max_seconds, action_limit = resolve_session_bounds(max_seconds, session_policy)
        self.clock = clock
        if touch_mode not in ('press-position','swipe-click'):
            raise ValueError('Fixed touch interaction mode required')
        if session_policy is not None and touch_mode != 'swipe-click':
            raise ValueError('Sustained session policy requires swipe-click mode')
        self.touch_mode=touch_mode
        if pose_mode not in ('direct','adaptive-jitter','adaptive-responsive','adaptive-vector','adaptive-vector-chunked','adaptive-vector-gain85'):
            raise ValueError('Fixed internal pointer mode required')
        pointer_type=DirectPosePointer
        if pose_mode=='adaptive-jitter':
            from adaptive_pose_pointer import AdaptivePosePointer
            pointer_type=AdaptivePosePointer
        elif pose_mode=='adaptive-responsive':
            from adaptive_pose_pointer import ResponsiveAdaptivePosePointer
            pointer_type=ResponsiveAdaptivePosePointer
        elif pose_mode in ('adaptive-vector','adaptive-vector-chunked'):
            from vector_adaptive_pose_pointer import VectorAdaptivePosePointer
            pointer_type=VectorAdaptivePosePointer
        elif pose_mode=='adaptive-vector-gain85':
            from vector_adaptive_pose_pointer import ReducedGainVectorAdaptivePosePointer
            pointer_type=ReducedGainVectorAdaptivePosePointer
        self.relative_encoding='chunks-le15' if pose_mode=='adaptive-vector-chunked' else 'single-frame'
        pointer_options = {'clock': clock, 'max_seconds': max_seconds}
        if session_policy is not None:
            pointer_options['session_policy'] = session_policy
        self.pointer = pointer_type(**pointer_options)
        regions = SurfaceRegions(x_min=-1768, x_max=-200, y_min=-1032, y_max=440,
                                 center_fraction=.65)
        if touch_mode=='swipe-click':
            from swipe_click import SwipeClick
            press_options = {'clock': clock, 'max_seconds': max_seconds,
                             'max_actions': action_limit}
            if session_policy is not None:
                press_options['session_policy'] = session_policy
            self.press=SwipeClick(self._emit,regions,**press_options)
        else:
            self.press = PositionPress(self._emit, regions, clock=clock,
                                       max_seconds=max_seconds, max_presses=16)
        self.emit = emit
        self.generation = None
        self.buttons_down = False
        self.closed = False
        self.failed = False
        self.reason = None

    def _emit(self, action, down):
        try:
            return self.emit(action, down)
        except BaseException:
            self.failed = self.closed = True
            self.reason = 'semantic-output-uncertain-destroy-own-device'
            self.generation = None
            self.pointer.stop(self.reason)
            # PositionPress/TouchClick marks itself failed and closed on an
            # uncertain write. Do not retry a possibly delivered transition.
            raise

    def bind(self, generation):
        if self.closed:
            return False
        if self.generation is not None:
            raise RuntimeError('Unbind previous link first')
        if not self.pointer.bind(generation):
            return False
        try:
            if not self.press.bind(generation):
                self.pointer.unbind(generation)
                return False
        except BaseException:
            self.pointer.unbind(generation)
            raise
        self.generation = generation
        self.buttons_down = False
        return True

    @staticmethod
    def _press_value(value, compact):
        if (type(value) not in (bytes, bytearray) or len(value) < 2 or
                value[0] not in (4, 5, 6)):
            return value
        # PositionPress accepts ordinary touch prefixes. Convert compact kind
        # 4/5/6 back to the equivalent 0/1/2 contact prefix. This bounded
        # extraction also preserves button suppression when sensor fields fail
        # validation; only a fully decoded value reaches the motion pointer.
        count = value[0] & 3
        prefix_length = (2, 13, 20)[count]
        if len(value) != prefix_length + 24:
            return value
        return bytes((count,)) + bytes(value[1:prefix_length])

    def feed(self, generation, value):
        if self.closed:
            return None
        if type(generation) is not int or generation != self.generation:
            self.pointer.feed(generation, value)
            self.press.feed(generation, value)
            return None
        compact = decode_compact_motion(value)
        press_value = self._press_value(value, compact)
        self.press.feed(generation, press_value)
        # Only fully validated compact 26/37/44-byte motion reaches the pose
        # pointer. Touch never moves the pointer; the selected touch policy alone
        # can translate a completed swipe into a semantic direction tap.
        mask = (press_value[1] if type(press_value) in (bytes, bytearray) and
                len(press_value) >= 2 else 0)
        down = bool(mask)
        if down:
            self.buttons_down = True
            self.pointer._clear_tracking()
            self._sync_children()
            return None
        released = self.buttons_down
        self.buttons_down = False
        if compact is None:
            valid_press_report = (type(press_value) in (bytes, bytearray) and
                                  ((len(press_value) == 2 and press_value[0] == 0) or
                                   decode_touch(press_value) is not None))
            if not valid_press_report:
                self.pointer._clear_tracking()
            self._sync_children()
            return None
        if released:
            # This released-pose report becomes the new baseline; no motion
            # accumulated during the physical button hold can catch up.
            self.pointer._clear_tracking()
        result = self.pointer.feed(generation, value)
        self._sync_children()
        return result

    def _sync_children(self):
        if self.pointer.closed or self.press.core.closed:
            self.closed = True
            self.generation = None
            if self.reason is None:
                self.reason = self.pointer.reason or self.press.core.reason or 'child-closed'

    def tick(self):
        if self.closed:
            return (0, 0)
        try:
            self.press.tick()
            if self.buttons_down:
                self.pointer._clear_tracking()
                self._sync_children()
                return (0, 0)
            result = self.pointer.tick()
            self._sync_children()
            return (0, 0) if result is None else result
        except BaseException:
            if self.press.core.summary()['requiresOwnDeviceDestroy']:
                self.failed = self.closed = True
                self.reason = 'semantic-output-uncertain-destroy-own-device'
                self.generation = None
                self.pointer.stop(self.reason)
            raise

    def unbind(self, generation):
        if type(generation) is not int or generation != self.generation:
            return False
        self.stop('link-loss')
        return True

    def stop(self, reason='requested'):
        if self.closed:
            return
        self.closed = True
        self.reason = reason
        self.generation = None
        self.pointer.stop(reason)
        try:
            self.press.stop(reason)
        finally:
            self.buttons_down = False

    def summary(self):
        return {'closed': self.closed, 'reason': self.reason,
                'touchMode':self.touch_mode,
                'requiresOwnDeviceDestroy': self.failed or self.press.core.failed,
                'activeGeneration': self.generation,
                'relativeEncoding': self.relative_encoding,
                'pointer': self.pointer.summary(), 'press': self.press.summary(),
                'nativeInputWrites': 0, 'deviceOrNetworkOpens': 0,
                'boundedSeconds': self.pointer.max_seconds,
                'policy': ('compact fused pose drives relative motion; completed swipe selects a direction; '
                           'physical press anywhere clicks' if self.touch_mode=='swipe-click' else
                           'compact fused pose drives relative motion; physical press position selects one semantic action')}
