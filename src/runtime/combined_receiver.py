"""Integration of the existing HID router and verified evdev writers.

No devices are opened here. The caller supplies already-verified output FDs.
This module does not connect Bluetooth or enable sensors. Motion remains
gated unless a test or a future independently verified device path
explicitly opts in.
"""
import time
from collections import deque
from gated_hidraw_router import GatedHidrawRouter
from input_router import InputRouter
from output_bridge import BTN_LEFT, KEY_ENTER, KEYS, _frame


class CombinedReceiver:
    def __init__(self, outputs, *, clock=time.monotonic, sensor_input_verified=False, session_policy=None, max_actions=12, action_history_limit=None):
        from input_session_policy import InputSessionPolicy
        limit = 16 if session_policy is None else session_policy.max_actions if type(session_policy) is InputSessionPolicy else 0
        if type(max_actions) is not int or not 1 <= max_actions <= limit:
            raise ValueError("bounded action budget required")
        if action_history_limit is not None and (type(action_history_limit) is not int or not 1 <= action_history_limit <= 256):
            raise ValueError("bounded action history required")
        if max_actions > 16 and action_history_limit is None:
            raise ValueError("sustained sessions require bounded action history")
        self.outputs = outputs
        self.max_actions = max_actions
        self.semantic_actions = 0
        self.actions = [] if action_history_limit is None else deque(maxlen=action_history_limit)
        self.action_history_limit = action_history_limit
        self.action_events = 0
        self.failed = False
        self.generation = None
        self.pending_direction = None
        self.center_output = None
        self.closed = False
        self.cleanup_error = None
        seconds = 30. if session_policy is None else session_policy.seconds
        self.router = InputRouter(self._emit, clock=clock, max_seconds=seconds,
                                  pose_mode='adaptive-vector-gain85',
                                  touch_mode='swipe-click', session_policy=session_policy)
        self.bridge = GatedHidrawRouter(self.router, sensor_input_verified=sensor_input_verified,
                                        session_policy=session_policy)

    def bind(self, generation):
        if self.closed or self.failed or self.generation is not None:
            return False
        if self.router.bind(generation):
            self.generation = generation
            return True
        return False

    def _emit(self, action, down):
        if type(down) is not bool:
            raise ValueError('invalid-action-state')
        if down and self.semantic_actions >= self.max_actions:
            self.failed = True
            raise RuntimeError('semantic-action-budget-exhausted')
        if action == 'center':
            if down:
                if self.center_output is not None:
                    raise RuntimeError('center-overlap')
                # Latch the destination until release, even if the mode changes.
                navigation = getattr(self.router, 'navigation', None)
                self.center_output = 'focus' if getattr(navigation, 'mode', None) == 'navigation' else 'pointer'
            elif self.center_output is None:
                raise RuntimeError('center-release-without-down')
            focused = self.center_output == 'focus'
            packet = _frame(KEY_ENTER if focused else BTN_LEFT, int(down))
            try:
                result = (self.outputs.select_frame if focused else self.outputs.click_frame)(packet)
            except BaseException:
                self.failed = True
                raise
            if down:
                self.semantic_actions += 1
            self.actions.append({'kind': 'focus-frame' if focused else 'click-frame', 'bytes': len(packet), 'value': int(down)})
            if not down:
                self.center_output = None
            self.action_events += 1
            return result
        if action not in KEYS:
            raise ValueError('unsupported-action')
        if down:
            if self.pending_direction is not None:
                raise RuntimeError('direction-overlap')
            try:
                self.outputs.key_pulse(action)
            except BaseException:
                self.failed = True
                raise
            self.semantic_actions += 1
            self.actions.append({"kind": "arrow", "direction": action})
            self.action_events += 1
            self.pending_direction = action
        else:
            if self.pending_direction != action:
                raise RuntimeError('direction-release-mismatch')
            self.pending_direction = None

    def _move(self, delta):
        if delta is None:
            return
        if not isinstance(delta, tuple) or len(delta) != 2:
            raise ValueError('invalid-pointer-delta')
        self.outputs.move_relative(*delta)

    def feed_raw(self, generation, report):
        if self.closed or self.failed or generation != self.generation or self.generation is None:
            return False
        self.feed_read(report)
        return True

    def feed_read(self, report):
        if self.closed:
            raise RuntimeError('receiver-closed')
        try:
            self._move(self.bridge.feed_read(self.generation, report))
        except BaseException:
            self.failed = True
            self._stop_after_error()
            raise

    def tick(self):
        if self.closed:
            raise RuntimeError('receiver-closed')
        try:
            self._move(self.router.tick())
        except BaseException:
            self.failed = True
            self._stop_after_error()
            raise

    def _stop_after_error(self):
        try:
            self.stop()
        except BaseException as exc:
            self.cleanup_error = type(exc).__name__

    def stop(self, reason="receiver-stop"):
        if self.closed:
            return
        self.closed = True
        try:
            self.router.stop(reason)
        finally:
            if not self.outputs.best_effort_release():
                raise RuntimeError('output-release-unverified')

    def summary(self):
        return {'actions': list(self.actions), 'failed': self.failed,
                'actionEvents': self.action_events,
                'actionHistoryTruncated': self.action_events > len(self.actions),
                'semanticActionCount': self.semantic_actions, 'maxActions': self.max_actions,
                'stopped': self.closed, 'rawReportsPersisted': False,
                'sensorEnableAttempted': False, 'motionGateOpen': self.bridge.sensor_input_verified,
                'router': self.router.summary(), 'bridge': self.bridge.summary()}
