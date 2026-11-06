"""One A1513 startup response can carry the button that woke the remote.

Main0241 and the Mac/TV captures place the queued button byte in FC/E0
responses of length 3 or 4. Require its actual release; never infer a button
from connection alone. This helper performs no I/O and never handles motion.
"""
import math
from system_buttons import observed_mask


def response_mask(report):
    if (type(report) in (bytes, bytearray) and len(report) in (3, 4)
            and report[:2] == b'\xfc\xe0'):
        return report[2]
    return None


class QueuedWakeButton:
    def __init__(self, *, enabled, mapping, holds, clock):
        self.enabled = enabled is True
        self.mapping, self.holds = dict(mapping), dict(holds or {})
        self.clock = clock
        self.started = self.last = clock()
        self.seen = False
        self.mask = self.pressed_at = self.action = None
        self.released = False

    def _valid(self):
        now = self.clock()
        if (not self.enabled or not math.isfinite(now) or now < self.last
                or not 0 <= now - self.started <= 3):
            self.cancel()
            return None
        self.last = now
        return now

    def feed(self, report):
        now = self._valid()
        if now is None:
            return
        response = response_mask(report)
        if response is None and type(report) in (bytes, bytearray) and report[:2] == b'\xfc\xe0':
            self.cancel()
            return
        mask = observed_mask(report) if response is None else response
        if mask is None:
            return
        if self.released:
            # A later deliberate press supersedes an undelivered wake action.
            if mask != 0:self.cancel()
            return
        if not self.seen:
            self.seen = True
            # Ordinary input keeps the existing neutral-before-press rule.
            # Only a first queued response can establish this wake press.
            if response is None or mask not in self.mapping or mask not in (1,2,4,8,16,32,128):
                self.cancel()
                return
            self.mask, self.pressed_at = mask, now
        elif mask == 0:
            self.action = (self.holds.get(self.mask, self.mapping[self.mask])
                           if now - self.pressed_at >= .716 else self.mapping[self.mask])
            self.released = True
        elif mask != self.mask:
            self.cancel()

    def ready(self):
        return self._valid() is not None and self.released

    def take(self):
        if not self.ready():
            return None
        action = self.action
        self.cancel()
        return action

    def cancel(self):
        self.enabled = False
        self.mask = self.pressed_at = self.action = None
        self.released = False


class QueuedWakeSurface(QueuedWakeButton):
    """One verified startup surface press; retain its actual release if early.

    The ordinary click recognizer owns the press after handoff. No held state
    is inferred from connection, and ordinary startup reports cannot arm this.
    """
    def __init__(self, *, enabled, clock):
        super().__init__(enabled=enabled, mapping={128:'center'}, holds={}, clock=clock)
        self.release_report = None

    def feed(self, report):
        released = self.released
        super().feed(report)
        if self.released and not released:
            self.release_report = bytes(report)

    def pending(self):
        return self._valid() is not None and self.mask == 128

    def take_press(self):
        report = self.release_report
        self.cancel()
        return report

    def cancel(self):
        super().cancel()
        self.release_report = None
