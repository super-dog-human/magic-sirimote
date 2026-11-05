"""Touch-surface swipe and physical-click recognizer.

This module performs no device or network I/O. Output is an injected
semantic callback ``emit(action, down)``. A cardinal swipe is emitted as a
nonblocking 60 ms direction pulse after contact ends; a physical surface
press emits center down/up.
"""
import math
import struct
import time

from position_press import SurfaceRegions
from touch_click import TouchClick, button_mask
from touch_coordinates import decode_touch


class SwipeClick:
    MAX_GAP_SECONDS = .150
    MAX_GESTURE_SECONDS = 2.000
    MIN_SWIPE_FRACTION = .18
    MIN_AXIS_RATIO = 1.5
    MAX_ACTIONS = 16
    SWIPE_PULSE_SECONDS = .060

    def __init__(self, emit, regions, *, clock=time.monotonic,
                 max_seconds=30, max_actions=16, session_policy=None, deferred_center=False):
        if not callable(emit):
            raise ValueError('An injected semantic emitter is required')
        if not isinstance(regions, SurfaceRegions):
            raise ValueError('Explicit calibrated surface required')
        from input_session_policy import resolve_session_bounds
        max_seconds, policy_actions = resolve_session_bounds(max_seconds, session_policy)
        action_limit = policy_actions if session_policy is not None else self.MAX_ACTIONS
        if type(max_actions) is not int or not 1 <= max_actions <= action_limit:
            raise ValueError('At most sixteen actions')
        if not callable(clock):
            raise ValueError('Finite monotonic clock required')
        self.emit, self.regions = emit, regions
        self._raw_clock = clock
        self._clock_error = False
        self._clock_value = None
        self._sample_last = None
        self._sample_clock()
        if self._clock_error:
            raise ValueError('Finite monotonic clock required')
        self.core = TouchClick(self._translate, max_seconds=max_seconds,
                               max_clicks=max_actions, clock=self._clock_proxy,
                               session_policy=session_policy, deferred_output=deferred_center)
        self.max_actions = max_actions
        self.swipes = dict.fromkeys(('up', 'down', 'left', 'right'), 0)
        self.stats = {'physicalClicks': 0, 'semanticEvents': 0,
                      'cancelledGestures': 0, 'rejectedSwipes': 0,
                      'blockedContactFrames': 0,
                      'twoContactStatePairs': dict.fromkeys(tuple(str(a)+'-'+str(b) for a in range(8) for b in range(8)), 0),
                      'invalidFrameKinds': dict.fromkeys(('multiple-contacts','unsupported-state','bad-mask','unrecognized'), 0),
                      'unsupportedFingerStates': dict.fromkeys(tuple(str(i) for i in range(8)), 0),
                      'cancelReasons': dict.fromkeys(('timeout','gap','button','invalid','blocked','bounds','unarmed','new-contact','stopped','other'), 0)}
        # Aggregate only; no coordinates, event timeline, or raw input is saved.
        self.stats['liftDiagnostics'] = dict.fromkeys(('recognized', 'belowThreshold',
            'ambiguousDirection', 'tailWouldMeetThreshold', 'tailChangesDirection',
            'tailOutOfBounds', 'liftWithoutGesture'), 0)
        self.stats['idleHoverFrames'] = 0
        self.gesture = None
        self.last_frame_at = None
        self.release_observed = False
        self.block_until_lift = False
        self.button_blocked = False
        self.button_release_seen = False
        self.button_lift_seen = False
        self._known_reject = False
        self._rejected_transition = None
        self.center_down_known = False
        self.center_suppressed = False
        self.pending_swipe = None

    def _sample_clock(self):
        try:
            value = self._raw_clock()
        except BaseException:
            self._clock_error = True
            return self._clock_value
        if (type(value) not in (int, float) or value < 0 or value > 1e12 or
                (type(value) is float and not math.isfinite(value)) or
                (self._sample_last is not None and value < self._sample_last)):
            self._clock_error = True
            return self._clock_value
        self._clock_value = value
        self._sample_last = value
        return value

    def _clock_proxy(self):
        return self._clock_value

    def _handle_clock_error(self):
        self._cancel()
        self.block_until_lift = True
        self._release_swipe()
        if self.core.closed:
            return
        try:
            # A live generation owns any accepted center-down transition.
            if self.core.down and self.core.generation is not None:
                self.core.stop('clock-invalid')
            elif self.core.down:
                self._fail_uncertain()
            else:
                self.core.stop('clock-invalid')
        except BaseException:
            self._fail_uncertain()
        self._sync_known_center()

    def _cancel(self, reason='other'):
        if self.gesture is not None:
            self.stats['cancelledGestures'] += 1
            self.stats['cancelReasons'][reason] += 1
        self.gesture = None

    def _in_bounds(self, x, y):
        return (type(x) in (int, float) and type(y) in (int, float) and
                math.isfinite(x) and math.isfinite(y) and
                self.regions.x_min <= x <= self.regions.x_max and
                self.regions.y_min <= y <= self.regions.y_max)

    def _fail_closed(self, actual_center_down=None):
        # Do not ask TouchClick.stop() to synthesize a release after uncertainty.
        self.core.failed = self.core.closed = True
        self.core.armed = False
        self.core.generation = None
        self.core.down = bool(actual_center_down)
        if not actual_center_down:
            self.core.pressed_at = None
        self.center_down_known = actual_center_down
        self.core.reason = 'write-uncertain-destroy-own-device'
        self._cancel()

    def _fail_uncertain(self):
        self._fail_closed(None)

    def _sync_known_center(self):
        if self.core.failed and self.center_down_known is not None:
            self.core.down = self.center_down_known

    def _semantic(self, action, down):
        try:
            result = self.emit(action, down)
        except BaseException:
            self._fail_uncertain()
            raise
        if result is False:
            self._known_reject = True
            self._rejected_transition = down
            return False
        self.stats['semanticEvents'] += 1
        return True

    def _release_swipe(self):
        """Release the one direction this sink knows it accepted, without retry."""
        if self.pending_swipe is None or self.core.failed:
            return False
        direction = self.pending_swipe['direction']
        self.pending_swipe = None
        if not self._semantic(direction, False):
            self.stats['rejectedSwipes'] += 1
            self._fail_uncertain()
            return False
        self.swipes[direction] += 1
        return True

    def _advance_swipe(self, now, *, force=False):
        if self.pending_swipe is None:
            return False
        if force or now - self.pending_swipe['started'] >= self.SWIPE_PULSE_SECONDS:
            return self._release_swipe()
        return False

    def _translate(self, packet):
        if len(packet) != 32:
            raise ValueError('Unexpected click-core frame')
        event = struct.unpack('=iiHHi', packet[:16])
        syn = struct.unpack('=iiHHi', packet[16:])
        if event[:4] != (0, 0, 1, 0x110) or event[4] not in (0, 1) or syn != (0, 0, 0, 0, 0):
            raise ValueError('Only reviewed physical-press transitions accepted')
        if event[4]:
            self._cancel('button')  # A center press owns this contact; no swipe tap too.
            if self.pending_swipe is not None:
                # Finish the accepted direction before honoring the physical press.
                # A failed release must never be followed by another action.
                if not self._release_swipe():
                    raise RuntimeError('swipe release unconfirmed before center')
            accepted = self._semantic('center', True)
            if accepted:
                self.center_down_known = True
                self.stats['physicalClicks'] += 1
            return len(packet)
        if self.center_suppressed:
            self.center_suppressed = False
            self.center_down_known = False
            return len(packet)
        accepted = self._semantic('center', False)
        if not accepted:
            # A rejected release leaves the output state uncertain to its owner.
            self._fail_closed(True)
        else:
            self.center_down_known = False
        return len(packet)

    def bind(self, generation):
        self._cancel()
        self.last_frame_at = None
        self.release_observed = False
        self.block_until_lift = False
        self.button_blocked = False
        self.button_release_seen = False
        self.button_lift_seen = False
        return self.core.bind(generation)

    def unbind(self, generation):
        if type(generation) is not int or generation != self.core.generation:
            return False
        self._cancel()
        self.last_frame_at = None
        self.release_observed = False
        self.block_until_lift = True
        self._release_swipe()
        result = self.core.unbind(generation)
        self._sync_known_center()
        return result

    def stop(self, reason='requested'):
        self._cancel('stopped')
        self.last_frame_at = None
        self._release_swipe()
        self.core.stop(reason)
        self._sync_known_center()

    def tick(self):
        self._sample_clock()
        if self._clock_error:
            self._handle_clock_error()
            return False
        now = self.core._now()
        if now is None:
            self._cancel()
            self._release_swipe()
            self._sync_known_center()
            return False
        if self.gesture is not None and now - self.gesture['last'] > self.MAX_GAP_SECONDS:
            self._cancel('gap')
            self.block_until_lift = True
        self._advance_swipe(now, force=(now - self.core.started >= self.core.max_seconds))
        result = self.core.tick()
        self._sync_known_center()
        return result

    def _swipe_direction(self, gesture, x, y):
        dx = (x - gesture['x']) / (self.regions.x_max - self.regions.x_min)
        dy = (y - gesture['y']) / (self.regions.y_max - self.regions.y_min)
        ax, ay = abs(dx), abs(dy)
        if max(ax, ay) < self.MIN_SWIPE_FRACTION:
            return None
        if ax >= self.MIN_AXIS_RATIO * ay:
            return 'right' if dx > 0 else 'left'
        if ay >= self.MIN_AXIS_RATIO * ax:
            return 'up' if dy > 0 else 'down'
        return None

    def _tap_swipe(self, direction, now):
        if (self.pending_swipe is not None or self.center_suppressed or
                self.center_down_known or self.core.down):
            self.stats['rejectedSwipes'] += 1
            return False
        while self.core.presses and self.core.presses[0] <= now - 1:
            self.core.presses.popleft()
        if (self.core.stats['pressAttempts'] >= self.max_actions or
                len(self.core.presses) >= self.core.MAX_PRESSES_PER_SECOND):
            self.stats['rejectedSwipes'] += 1
            self.core.stats['rateLimited'] += 1
            return False
        self.core.presses.append(now)
        self.core.stats['pressAttempts'] += 1
        if not self._semantic(direction, True):
            self.stats['rejectedSwipes'] += 1
            return False
        self.pending_swipe = {'direction': direction, 'started': now}
        return True

    def feed(self, generation, value):
        before_events = self.stats['semanticEvents']
        self._sample_clock()
        if self._clock_error:
            self._handle_clock_error()
            self._sync_known_center()
            return self.stats['semanticEvents'] != before_events
        now = self.core._now()
        if now is None:
            self._cancel()
            self._release_swipe()
            self.block_until_lift = True
            self._sync_known_center()
            return self.stats['semanticEvents'] != before_events
        self._advance_swipe(now, force=(now - self.core.started >= self.core.max_seconds))
        if self.core.closed:
            self._cancel()
            self.block_until_lift = True
            return self.stats['semanticEvents'] != before_events
        current_generation = type(generation) is int and generation == self.core.generation and self.core.generation is not None
        if not current_generation:
            self._cancel()
            self.last_frame_at = None
            self.block_until_lift = True
            self.core.feed(generation, value)
            self._sync_known_center()
            return self.stats['semanticEvents'] != before_events
        if self.last_frame_at is not None and now - self.last_frame_at > self.MAX_GAP_SECONDS:
            self._cancel('gap')
            self.block_until_lift = True
        self.last_frame_at = now

        mask = button_mask(value)
        decoded = decode_touch(value)
        valid_button_only = type(value) in (bytes, bytearray) and len(value) == 2 and value[0] == 0
        touched = False
        lift = False
        active_position = None
        invalid = False
        if decoded is not None:
            fingers = decoded['fingers']
            if len(fingers) == 2:
                pair = str(fingers[0]['state']) + '-' + str(fingers[1]['state'])
                self.stats['twoContactStatePairs'][pair] += 1
            if len(fingers) != 1 or mask not in (0, 0x80):
                invalid = True
            else:
                finger = fingers[0]
                if finger['state'] in (3, 4, 5, 6):
                    touched = True
                    active_position = (finger['x'], finger['y'])
                elif finger['state'] in (0, 7):
                    lift = True
                elif finger['state'] in (1, 2) and self.gesture is None and mask == 0:
                    # Preliminary/light contact: neither a lift nor an
                    # established swipe. It cannot start or finish a gesture.
                    self.stats['idleHoverFrames'] += 1
                else:
                    invalid = True
        elif valid_button_only and mask in (0, 0x80):
            lift = True
        else:
            invalid = True

        if invalid:
            if decoded is None:
                invalid_kind = 'unrecognized'
            elif len(decoded['fingers']) != 1:
                invalid_kind = 'multiple-contacts'
            elif mask not in (0, 0x80):
                invalid_kind = 'bad-mask'
            else:
                invalid_kind = 'unsupported-state'
                self.stats['unsupportedFingerStates'][str(decoded['fingers'][0]['state'])] += 1
            self.stats['invalidFrameKinds'][invalid_kind] += 1

        # Buttons take precedence over lift interpretation. Any pressed button
        # owns the contact and blocks swipe recognition through release and lift.
        if mask is None or mask != 0:
            self._cancel('button')
            self.block_until_lift = True
            self.button_blocked = True
            self.button_release_seen = False
            self.button_lift_seen = False
        elif invalid:
            self._cancel('invalid')
            self.release_observed = False
            self.block_until_lift = True
        elif self.block_until_lift or self.button_blocked:
            if touched:
                self.stats['blockedContactFrames'] += 1
            self._cancel('blocked')
        elif touched:
            x, y = active_position
            if finger['state'] in (5, 6):
                # End-of-contact coordinates may be noisy. Preserve the last
                # established position and never start a gesture from them.
                if self.gesture is not None:
                    if now - self.gesture['start'] > self.MAX_GESTURE_SECONDS:
                        self._cancel('timeout'); self.block_until_lift = True
                    elif now - self.gesture['last'] > self.MAX_GAP_SECONDS:
                        self._cancel('gap'); self.block_until_lift = True
                    else:
                        self.gesture['last'] = now
                        if self._in_bounds(x, y):
                            self.gesture['tail'] = (x, y)
                        else:
                            self.stats['liftDiagnostics']['tailOutOfBounds'] += 1
            elif not self._in_bounds(x, y):
                self._cancel('bounds')
                self.block_until_lift = True
            elif not self.release_observed or not self.core.armed:
                self._cancel('unarmed')
            elif self.gesture is not None and now - self.gesture['start'] > self.MAX_GESTURE_SECONDS:
                self._cancel('timeout')
                self.block_until_lift = True
            elif finger['state'] == 3:
                # A new contact start resets its origin; it never inherits motion.
                self._cancel('new-contact')
                self.gesture = {'x': x, 'y': y, 'last_x': x, 'last_y': y,
                                'start': now, 'last': now}
            elif self.gesture is None:
                self.gesture = {'x': x, 'y': y, 'last_x': x, 'last_y': y,
                                'start': now, 'last': now}
            elif now - self.gesture['last'] > self.MAX_GAP_SECONDS:
                self._cancel('gap')
                self.block_until_lift = True
            else:
                self.gesture['last_x'] = x
                self.gesture['last_y'] = y
                self.gesture['last'] = now
                self.gesture.pop('tail', None)
        elif lift:
            # A lift can close a gesture only if the entire contact remained clear.
            if self.gesture is not None:
                gap = now - self.gesture['last']
                duration = now - self.gesture['start']
                if gap > self.MAX_GAP_SECONDS or duration > self.MAX_GESTURE_SECONDS:
                    self._cancel('gap' if gap > self.MAX_GAP_SECONDS else 'timeout')
                    self.block_until_lift = True
                else:
                    x, y = self.gesture['last_x'], self.gesture['last_y']
                    direction = self._swipe_direction(self.gesture, x, y)
                    diag = self.stats['liftDiagnostics']
                    dx = abs((x - self.gesture['x']) / (self.regions.x_max - self.regions.x_min))
                    dy = abs((y - self.gesture['y']) / (self.regions.y_max - self.regions.y_min))
                    if direction is not None:
                        diag['recognized'] += 1
                    elif max(dx, dy) < self.MIN_SWIPE_FRACTION:
                        diag['belowThreshold'] += 1
                    else:
                        diag['ambiguousDirection'] += 1
                    tail = self.gesture.get('tail')
                    if tail is not None:
                        tail_direction = self._swipe_direction(self.gesture, *tail)
                        if direction is None and tail_direction is not None:
                            diag['tailWouldMeetThreshold'] += 1
                        elif direction is not None and tail_direction is not None and direction != tail_direction:
                            diag['tailChangesDirection'] += 1
                    self.gesture = None
                    if direction is not None:
                        self._tap_swipe(direction, now)
            else:
                self.stats['liftDiagnostics']['liftWithoutGesture'] += 1

        # A button release during active contact is necessary but not sufficient.
        if mask == 0 and self.button_blocked:
            self.button_release_seen = True
            if lift:
                self.button_lift_seen = True
            if self.button_lift_seen:
                self.button_blocked = False
                self.button_release_seen = False
                self.button_lift_seen = False
        if lift and mask == 0:
            self.release_observed = True
            self.block_until_lift = False

        self._known_reject = False
        self._rejected_transition = None
        self.core.feed(generation, value)
        if self._known_reject:
            # A rejected press was not written; a rejected release stays latched.
            if self._rejected_transition:
                self.core.stats['pressesWritten'] -= 1
                self.core.down = False
                self.core.pressed_at = None
                self.core.armed = False
            else:
                self.core.stats['releasesWritten'] -= 1
                self.core.down = True
                self.center_down_known = True
        if self._clock_error:
            self._handle_clock_error()
        self._sync_known_center()
        return self.stats['semanticEvents'] != before_events

    def summary(self):
        return {**self.stats, 'swipes': dict(self.swipes),
                'safety': self.core.summary(), 'surface': 'explicit calibrated bounds',
                'cursorEvents': 0, 'liveKeyWrites': 0,
                'deviceOrNetworkOpens': 0, 'rawDataRetained': False,
                'policy': 'single cardinal swipe tap after lift; physical press maps to center'}
