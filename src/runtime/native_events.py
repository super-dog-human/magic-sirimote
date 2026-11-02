"""Pure semantic-to-Linux-input-event adapter; opens no device itself.

The caller must inject its own classified mouse sink and, when arrows are
enabled, a separately owned/classified keyboard sink. This module never
expands an existing mouse's declared capabilities.
"""
import math
import struct
import time


_FORMAT = '=iiHHi'  # Matches TV-local candidates: 32-bit timeval + type/code/value.
_EVENT_SIZE = struct.calcsize(_FORMAT)
_SYN_REPORT = (0, 0, 0, 0, 0)
_EV_KEY = 1
_BTN_LEFT = 0x110
_KEYS = {'up': 103, 'down': 108, 'left': 105, 'right': 106}


def _record(kind, code, value):
    return struct.pack(_FORMAT, 0, 0, kind, code, value)


def _frame(code, value):
    return _record(_EV_KEY, code, value) + struct.pack(_FORMAT, *_SYN_REPORT)


class NativeEventSink:
    """One-action latch over distinct injected sinks, with no write retries."""
    def __init__(self, mouse_writer, *, keyboard_writer=None, max_seconds=30., clock=time.monotonic,
                 session_policy=None):
        from input_session_policy import resolve_session_bounds
        max_seconds, _ = resolve_session_bounds(max_seconds, session_policy)
        self.mouse_writer, self.keyboard_writer, self.clock = mouse_writer, keyboard_writer, clock
        self.started = self.last_clock = clock()
        if type(self.started) not in (int, float) or not math.isfinite(self.started):
            raise ValueError('Finite monotonic clock required')
        self.max_seconds = max_seconds
        self.active = None
        self.active_writer = None
        self.closed = self.failed = False
        self.reason = None
        self.events = 0

    def _writer_for(self, action):
        return self.mouse_writer if action == 'center' else self.keyboard_writer

    def _send(self, action, down, writer):
        code = _BTN_LEFT if action == 'center' else _KEYS[action]
        packet = _frame(code, int(down))
        try:
            written = writer(packet)
            if written != len(packet):
                raise OSError('Partial input-event frame; no retry; destroy owned device')
        except BaseException:
            # Delivery is unknown. Forget local held state and never send a
            # speculative release to a device whose state cannot be trusted.
            self.active = self.active_writer = None
            self.failed = self.closed = True
            self.reason = 'write-uncertain-destroy-own-device'
            raise
        self.events += 1

    def _check_time(self):
        if self.closed:
            return False
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < self.last_clock:
            self.stop('clock-invalid')
            return False
        self.last_clock = now
        if now - self.started >= self.max_seconds:
            self.stop('deadline')
            return False
        return True

    def feed(self, action, down):
        if action not in ('center', 'up', 'down', 'left', 'right') or type(down) is not bool:
            raise ValueError('Expected one supported semantic action and a boolean transition')
        if not self._check_time():
            return False
        if down:
            if self.active is not None:
                return False
            writer = self._writer_for(action)
            if writer is None:
                return False
            self._send(action, True, writer)
            self.active, self.active_writer = action, writer
            return True
        if self.active != action:
            return False
        self._send(action, False, self.active_writer)
        self.active = self.active_writer = None
        return True

    def release_all(self):
        """Release one action only when this sink knows which action is held."""
        if self.closed or self.failed or self.active is None:
            return False
        action = self.active
        self._send(action, False, self.active_writer)
        self.active = self.active_writer = None
        return True

    def stop(self, reason='requested'):
        if self.closed:
            return False
        self.closed = True
        self.reason = reason
        if self.active is not None and not self.failed:
            action = self.active
            self._send(action, False, self.active_writer)
            self.active = self.active_writer = None
        return True

    def summary(self):
        return {'closed': self.closed, 'failed': self.failed, 'reason': self.reason,
                'activeAction': self.active, 'eventsWritten': self.events,
                'requiresOwnDeviceDestroy': self.failed,
                'automaticWriteRetries': 0, 'deviceOrNetworkOpens': 0,
                'eventFormat': _FORMAT, 'eventBytes': _EVENT_SIZE,
                'centerSink': 'mouse', 'directionSink': 'keyboard',
                'keyboardEnabled': self.keyboard_writer is not None,
                'sessionSeconds': self.max_seconds}
