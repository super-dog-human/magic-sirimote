"""Bounded candidate: physical surface press -> BTN_LEFT press/release.

Pure injected writer, no device/network opens. NOT wired into a live runner.
The runtime must supply only its verified, newly created mouse FD and call
tick() during silence; on write uncertainty it must destroy that own device.
Native left-click equivalence to LG's centre/OK is not yet hardware-tested.
"""
from collections import deque
import math
import struct
import time
from touch_coordinates import decode_touch


def button_mask(value):
    if type(value) not in (bytes, bytearray):
        return None
    if len(value) == 2 and value[0] == 0:
        return value[1]
    decoded = decode_touch(value)
    return decoded['buttons'] if decoded is not None else None


class TouchClick:
    MAX_HOLD_SECONDS = 2.0
    MAX_PRESSES_PER_SECOND = 4

    def __init__(self, writer, *, max_seconds=120, max_clicks=6, clock=time.monotonic,
                 session_policy=None):
        from input_session_policy import resolve_session_bounds
        max_seconds, policy_actions = resolve_session_bounds(
            max_seconds, session_policy, default_seconds=30, default_actions=16,
            legacy_max_seconds=300)
        click_limit = policy_actions if session_policy is not None else 16
        if type(max_clicks) is not int or not 1 <= max_clicks <= click_limit:
            raise ValueError('A finite click budget is required')
        self.writer, self.clock = writer, clock
        self.started = self.last_clock = clock()
        if not math.isfinite(self.started):
            raise ValueError('Finite monotonic clock required')
        self.max_seconds, self.max_clicks = max_seconds, max_clicks
        self.generation, self.highest_generation = None, 0
        self.armed = self.down = self.closed = self.failed = False
        self.pressed_at = None
        self.presses = deque()
        self.reason = None
        self.stats = dict.fromkeys(('pressAttempts','pressesWritten','releasesWritten',
                                   'physicalClickPairs','forcedReleases','rateLimited',
                                   'ignoredReports','staleReports'),0)

    def _write(self, pressed, forced=False):
        # Only this mouse button and SYN_REPORT; never KEY_OK, IR, a second
        # mouse, an arbitrary key or a button-repeat (value 2).
        packet = struct.pack('=iiHHi',0,0,1,0x110,int(pressed)) + struct.pack('=iiHHi',0,0,0,0,0)
        if pressed:
            self.stats['pressAttempts'] += 1
        try:
            if self.writer(packet) != len(packet):
                raise OSError('Partial button frame; no retry; destroy own device')
        except BaseException:
            self.failed = self.closed = True
            self.armed = False
            self.generation = None
            self.reason = 'write-uncertain-destroy-own-device'
            raise
        self.down = pressed
        if pressed:
            self.stats['pressesWritten'] += 1
        else:
            self.pressed_at = None
            self.stats['releasesWritten'] += 1
            self.stats['forcedReleases' if forced else 'physicalClickPairs'] += 1

    def stop(self, reason='requested'):
        if self.closed:
            return
        self.closed = True
        self.reason = reason
        self.generation = None
        self.armed = False
        if self.down:
            self._write(False,forced=True)

    def _now(self):
        if self.closed:
            return None
        now = self.clock()
        if not math.isfinite(now) or now < self.last_clock:
            self.stop('clock-invalid')
            return None
        self.last_clock = now
        if now - self.started >= self.max_seconds:
            self.stop('deadline')
            return None
        return now

    def bind(self,generation):
        if type(generation) is not int or generation <= self.highest_generation:
            raise ValueError('Fresh link generation required')
        if self._now() is None:
            return False
        if self.generation is not None:
            raise RuntimeError('Unbind previous link first')
        self.generation = self.highest_generation = generation
        # First observe ALL buttons released. A held button at startup or on
        # reconnect must not become a new click.
        self.armed = False
        return True

    def unbind(self,generation):
        if type(generation) is not int or generation != self.generation:
            return False
        self.generation = None
        self.armed = False
        if self.down:
            self._write(False,forced=True)
        return True

    def tick(self):
        now = self._now()
        if now is None:
            return False
        if self.down and now - self.pressed_at >= self.MAX_HOLD_SECONDS:
            self.armed = False
            self._write(False,forced=True)
            return True
        return False

    def feed(self,generation,value):
        now = self._now()
        if now is None:
            return False
        if type(generation) is not int or generation != self.generation or self.generation is None:
            self.stats['staleReports'] += 1
            return False
        # A delayed held report cannot bypass the periodic hold watchdog.
        if self.down and now - self.pressed_at >= self.MAX_HOLD_SECONDS:
            self.tick()
        mask = button_mask(value)
        if mask is None:
            self.stats['ignoredReports'] += 1
            return False
        if mask != 0x80:
            wrote = self.down
            if self.down:
                self._write(False,forced=(mask != 0))
            self.armed = mask == 0
            return wrote
        if not self.armed or self.down:
            return False
        while self.presses and self.presses[0] <= now - 1:
            self.presses.popleft()
        if self.stats['pressAttempts'] >= self.max_clicks or len(self.presses) >= self.MAX_PRESSES_PER_SECOND:
            self.stats['rateLimited'] += 1
            self.armed = False
            return False
        self.presses.append(now)
        self.pressed_at = now
        self._write(True)
        return True

    def summary(self):
        return {**self.stats,'closed':self.closed,'reason':self.reason,'buttonDown':self.down,
                'requiresOwnDeviceDestroy':self.failed,'activeGeneration':self.generation,
                'wheelEvents':0,'keyboardEvents':0,'irTransmissions':0,
                'automaticWriteRetries':0,'deviceOrNetworkOpens':0}
