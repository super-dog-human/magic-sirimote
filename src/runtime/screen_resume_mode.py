"""Revalidate sensor mode after an observed screen-off/on transition.

Use the existing connection. A fresh, bounded selector/read transaction checks
mode before any enable, and verifies the result. No connection or CCCD writes.
All calls run on the receiver thread; their pump keeps navigation responsive.
The TV can refuse the enable just after the screen returns, so an explicit
refusal is checked again later. A transport failure is never repeated.
"""
import time
import json

RETRY_DELAYS = (.5, 1, 2, 2, 2)


def check_mode(*, read, enable, record, guard):
    def checked():
        if guard() is not True:
            raise RuntimeError('screen-resume-control-lost')

    checked()
    mode = read()
    checked()
    if type(mode) is not int or mode not in (0, 1):
        raise RuntimeError('screen-resume-mode-unconfirmed')
    if mode == 1:
        return False
    if record({'stage': 'sensor-resume-intent'}) is not True:
        raise RuntimeError('screen-resume-intent-unrecorded')
    checked()
    if enable() is not True:
        raise RuntimeError('screen-resume-enable-unconfirmed')
    checked()
    mode = read()
    checked()
    if type(mode) is not int or mode != 1:
        raise RuntimeError('screen-resume-readback-unconfirmed')
    if record({'stage': 'sensor-resume-ack'}) is not True:
        raise RuntimeError('screen-resume-ack-unrecorded')
    return True


def restore_session_mode(session, *, pump, guard, clock=time.monotonic):
    from borrowed_mode_reader import BorrowedModeReader
    from borrowed_gatt_view import TARGET, ADAPTER
    from native_mode_session import NativeModeClient, SET, ack

    def valid():
        return (session.state == 'active' and not session.stop_attempted
                and guard() is True and session.control_valid() is True)

    if not valid():
        raise RuntimeError('screen-resume-control-lost')
    generation, client_id = session.view.generation, session.view.client_id
    activation = NativeModeClient(generation=generation, client_id=client_id,
                                  pump=pump, guard=valid, clock=clock)
    reader = BorrowedModeReader(activation, exclusive_feature_guard=valid, clock=clock)
    reader.bind_borrowed(link={'remote': TARGET, 'adapter': ADAPTER,
                              'generation': generation, 'connected': True,
                              'connecting': False, 'paired': True},
                         client_id=client_id, control_valid=valid)

    # The original session writer retains responsibility for final cleanup.
    def enable():
        activation.enable_allowed = True
        reply = activation(SET, {'address': TARGET, 'reportType': 'feature',
                                 'reportData': [240, 160, 1]}, timeout=6)
        return ack(reply)

    try:
        return check_mode(read=lambda: reader.read(generation)['mode'],
                          enable=enable, record=session.record, guard=valid)
    finally:
        reader.close('screen-resume-check-ended')


class ScreenResumeMode:
    """Coalesce screen observations without changing the connection generation."""
    def __init__(self, screen, session, *, live, abort, clock,
                 restore=restore_session_mode):
        self.screen, self.session = screen, session
        self.live, self.abort, self.clock, self.restore = live, abort, clock, restore
        self.completed = 0
        self.ready = True
        self.running = False
        self.failed = False
        self.sequence = 0
        self.attempts = 0
        self.retry_at = None

    def tick(self, pump):
        if self.running or self.failed:
            return
        sequence = self.screen.resume_sequence()
        if sequence <= self.completed or self.screen.blocked():
            return
        if sequence != self.sequence:
            self.sequence, self.attempts, self.retry_at = sequence, 0, None
        if self.retry_at is not None and self.clock() < self.retry_at:
            return
        self.ready = False
        self.running = True
        deadline = self.clock() + 15

        def valid():
            return (not self.abort() and self.live() is True
                    and self.clock() < deadline and not self.screen.blocked()
                    and self.screen.resume_sequence() == sequence)

        try:
            if not valid():
                raise RuntimeError('screen-resume-control-lost')
            self.restore(self.session, pump=pump, guard=valid, clock=self.clock)
            if not valid():
                raise RuntimeError('screen-resume-control-lost')
            self.completed = sequence
            self.ready = True
        except Exception as error:
            # A mode-check failure must not take working navigation down with
            # the gyro. Keep motion gated and retain cleanup ownership. Each
            # attempt reads mode first, so a repeat only follows a confirmed
            # zero. Subclasses and other types mean the transport is uncertain.
            lost = self.abort() or self.live() is not True
            retryable = type(error) is RuntimeError and not lost
            if retryable and self.attempts < len(RETRY_DELAYS):
                self.retry_at = self.clock() + RETRY_DELAYS[self.attempts]
                self.attempts += 1
                return
            reasons = ('screen-resume-control-lost', 'screen-resume-mode-unconfirmed',
                       'screen-resume-intent-unrecorded', 'screen-resume-enable-unconfirmed',
                       'screen-resume-readback-unconfirmed', 'screen-resume-ack-unrecorded')
            reason = str(error) if str(error) in reasons else type(error).__name__
            print(json.dumps({'stage': 'screen-resume-mode', 'status': 'failed',
                              'reason': reason}), flush=True)
            if retryable:
                # Refused every time: the next observed resume gets a new budget.
                self.retry_at = float('inf')
            else:
                self.failed = True
            if lost:
                raise
        finally:
            self.running = False
