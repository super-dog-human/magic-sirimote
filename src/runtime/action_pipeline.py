"""Offline bridge from B-style transient HID values to narrow output callbacks.

This module opens no device and sends nothing itself. A caller must provide an
exact-target B read FD and separately verified, owned output callbacks.
"""
from touch_click import TouchClick
from touch_dpad import TouchDpad

REPORT_ID_TOUCH = 0xFC
BTN_LEFT = 0x110
EV_KEY = 1
KEY_BYTES = 96


def touch_value(raw):
    """Strip the observed FC report ID; accept only recognized touch values.

    Button-only two-byte values are passed through for TouchClick's existing
    button decoder. Unknown reports are never forwarded to an action decoder.
    """
    if type(raw) is not bytes:
        return None
    if len(raw) == 2:
        return raw
    if len(raw) not in (14, 21) or raw[0] != REPORT_ID_TOUCH:
        return None
    from touch_coordinates import decode_touch
    value = raw[1:]
    return value if decode_touch(value) is not None else None


def has_capability(bitmap, code):
    return (type(bitmap) is bytes and len(bitmap) >= (code // 8) + 1 and
            bool(bitmap[code // 8] & (1 << (code % 8))))


def require_clickable_mouse_capabilities(event_types, key_types):
    """Require ClickableMouse to advertise REL_X/Y and BTN_LEFT before use."""
    if not all(has_capability(event_types, code) for code in (0, EV_KEY, 2)):
        raise RuntimeError('ClickableMouse-missing-event-capabilities')
    if not all(has_capability(key_types, code) for code in (BTN_LEFT,)):
        raise RuntimeError('ClickableMouse-missing-BTN_LEFT')
    return True


class ActionPipeline:
    """Route decoded swipes to key pulses and physical presses to BTN_LEFT.

    `key_pulse(direction)` must use the existing Builtin writer's checked
    down/up/release verification. `write_click_frame(packet)` writes exactly
    one already-framed TouchClick packet to a separately verified click sink.
    Both callbacks must raise on uncertain/partial writes; then the pipeline
    stops and accepts no further input.
    """
    def __init__(self, key_pulse, write_click_frame, *, clock, max_seconds=30,
                 max_actions=4):
        if not callable(key_pulse) or not callable(write_click_frame):
            raise ValueError('Narrow output callbacks required')
        if type(max_actions) is not int or not 1 <= max_actions <= 16:
            raise ValueError('Bounded action budget required')
        self.key_pulse = key_pulse
        self.write_click_frame = write_click_frame
        self.failed = False
        self.stopped = False
        self.actions = []
        self.max_actions = max_actions
        self.semantic_actions = 0
        self.decoder = TouchDpad(self._direction, clock=clock,
                                 max_seconds=max_seconds, max_steps=max_actions)
        self.clicker = TouchClick(self._click_frame, clock=clock,
                                  max_seconds=max_seconds, max_clicks=max_actions)
        self.generation = None

    def bind(self, generation):
        if self.stopped or self.failed:
            return False
        accepted = self.decoder.bind(generation)
        if not accepted:
            return False
        try:
            if not self.clicker.bind(generation):
                self.decoder.unbind(generation)
                return False
        except BaseException:
            self.decoder.unbind(generation)
            raise
        self.generation = generation
        return True

    def _direction(self, direction):
        if self.failed or self.stopped:
            raise RuntimeError('pipeline-not-active')
        if direction not in ('up', 'down', 'left', 'right'):
            raise RuntimeError('unrecognized-direction')
        if self.semantic_actions >= self.max_actions:
            self.failed = True
            raise RuntimeError('semantic-action-budget-exhausted')
        try:
            self.key_pulse(direction)
            self.semantic_actions += 1
            self.actions.append({'kind': 'arrow', 'direction': direction})
        except BaseException:
            self.failed = True
            raise

    def _click_frame(self, packet):
        from output_bridge import EVENT, EV_KEY, EV_SYN, SYN_REPORT, BTN_LEFT
        if type(packet) is not bytes or len(packet) != 2 * EVENT.size:
            self.failed = True
            raise ValueError('invalid-click-frame-size')
        ev = EVENT.unpack(packet[:EVENT.size])
        syn = EVENT.unpack(packet[EVENT.size:])
        if (ev[:4] != (0, 0, EV_KEY, BTN_LEFT) or ev[4] not in (0, 1) or
                syn != (0, 0, EV_SYN, SYN_REPORT, 0)):
            self.failed = True
            raise ValueError('click-frame-outside-BTN_LEFT-policy')
        is_release = ev[4] == 0
        if (self.failed or self.stopped) and not is_release:
            raise RuntimeError('pipeline-not-active')
        if not is_release:
            if self.semantic_actions >= self.max_actions:
                self.failed = True
                raise RuntimeError('semantic-action-budget-exhausted')
            self.semantic_actions += 1
        try:
            self.write_click_frame(packet)
            self.actions.append({'kind': 'click-frame', 'bytes': len(packet),'value':ev[4]})
            return len(packet)
        except BaseException:
            self.failed = True
            raise

    def feed_raw(self, generation, raw):
        if self.stopped or self.failed:
            return False
        value = touch_value(raw)
        if value is None:
            return False
        # The two existing state machines see the same validated value. The
        # D-pad ignores button-bearing frames; TouchClick ignores swipe-only
        # frames, preserving one output class per recognized interaction.
        self.decoder.feed(generation, value)
        self.clicker.feed(generation, value)
        return True

    def tick(self):
        if self.stopped or self.failed:
            return
        self.decoder.tick()
        self.clicker.tick()

    def unbind(self, generation):
        if self.generation != generation:
            return False
        self.decoder.unbind(generation)
        self.clicker.unbind(generation)
        self.generation = None
        return True

    def stop(self, reason='requested'):
        if self.stopped:
            return
        self.stopped = True
        failure = None
        try:
            self.clicker.stop(reason)
        except BaseException as e:
            self.failed = True
            failure = e
        finally:
            self.decoder.stop(reason)
            self.generation = None
        if failure is not None:
            raise failure

    def summary(self):
        return {'actions': list(self.actions), 'failed': self.failed,
                'semanticActionCount':self.semantic_actions,'maxActions':self.max_actions,
                'stopped': self.stopped, 'rawReportsPersisted': False,
                'sensorEnableAttempted': False,
                'decoder': self.decoder.summary(),
                'clicker': self.clicker.summary()}
