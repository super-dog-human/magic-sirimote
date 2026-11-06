import unittest

from position_press import SurfaceRegions
from swipe_click import SwipeClick


def touch(x, y, *, state=3, buttons=0):
    x &= 0xfff
    y &= 0xfff
    packed = ((y & 0xf) << 4) | ((x >> 8) & 0xf)
    high = (y >> 4) & 0xff
    return bytes((1, buttons, 0x32, 1, 0, 0, x & 0xff, packed, high, 0, 0, 0, state))


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def step(self, seconds=.02):
        self.now += seconds


class SwipeClickTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.events = []
        self.regions = SurfaceRegions(x_min=-100, x_max=100, y_min=-100, y_max=100)
        self.recognizer = SwipeClick(lambda action, down: self.events.append((action, down)),
                                     self.regions, clock=self.clock)
        self.recognizer.bind(1)
        self.generation = 1
        # Establish all-buttons-released baseline.
        self.recognizer.feed(1, b'\x00\x00')

    def step_feed(self, value, seconds=.02):
        self.clock.step(seconds)
        return self.recognizer.feed(self.generation, value)

    def swipe(self, direction):
        starts = {'right': (-80, 0), 'left': (80, 0), 'up': (0, -80), 'down': (0, 80)}
        ends = {'right': (0, 0), 'left': (0, 0), 'up': (0, 0), 'down': (0, 0)}
        # Deltas use enough normalized travel while staying inside calibration.
        x0, y0 = starts[direction]
        if direction == 'right': end = (0, y0)
        elif direction == 'left': end = (0, y0)
        elif direction == 'up': end = (x0, 0)
        else: end = (x0, 0)
        self.step_feed(touch(x0, y0, state=3))
        self.step_feed(touch(*end, state=4))
        self.step_feed(touch(*end, state=7))
        self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS)
        self.recognizer.tick()

    def swipe_frames(self, direction):
        starts = {'right': (-80, 0), 'left': (80, 0), 'up': (0, -80), 'down': (0, 80)}
        x0, y0 = starts[direction]
        end = (0, y0) if direction in ('right', 'left') else (x0, 0)
        self.step_feed(touch(x0, y0, state=3))
        self.step_feed(touch(*end, state=4))
        self.step_feed(touch(*end, state=7))

    def test_all_four_cardinal_swipes_emit_one_tap_after_lift(self):
        for direction in ('right', 'left', 'up', 'down'):
            self.events.clear()
            self.swipe(direction)
            self.assertEqual(self.events, [(direction, True), (direction, False)])

    def test_fresh_swipes_after_silent_released_idle_are_not_dropped(self):
        for direction in ('right', 'left', 'up', 'down'):
            self.clock.step(3)
            self.recognizer.tick()
            self.events.clear()
            self.swipe(direction)
            self.clock.step(.001)
            self.recognizer.tick()
            self.assertEqual(self.events, [(direction, True), (direction, False)])

    def test_silent_gap_during_contact_still_requires_lift(self):
        self.step_feed(touch(-80, 0, state=3))
        self.clock.step(1)
        self.recognizer.tick()
        self.swipe('right')
        self.assertEqual(self.events, [])
        self.swipe('left')
        self.assertEqual(self.events, [('left', True), ('left', False)])

    def test_idle_does_not_turn_continuation_into_new_contact(self):
        self.clock.step(3)
        self.step_feed(touch(-80, 0, state=4))
        self.step_feed(touch(0, 0, state=4))
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])

    def test_corner_trajectories_are_valid_swipes(self):
        self.step_feed(touch(-100, -100, state=3))
        self.step_feed(touch(-20, -100, state=4))
        self.assertTrue(self.step_feed(touch(-20, -100, state=7)))
        self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS)
        self.recognizer.tick()
        self.assertEqual(self.events, [('right', True), ('right', False)])

    def test_swipe_pulse_releases_only_after_sixty_milliseconds(self):
        self.swipe_frames('right')
        self.assertEqual(self.events, [('right', True)])
        self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS - .001)
        self.recognizer.tick()
        self.assertEqual(self.events, [('right', True)])
        self.clock.step(.001)
        self.recognizer.tick()
        self.assertEqual(self.events, [('right', True), ('right', False)])
        self.assertEqual(self.recognizer.summary()['swipes']['right'], 1)

    def test_feed_releases_due_pulse_before_processing_next_action(self):
        self.swipe_frames('right')
        self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS)
        self.recognizer.feed(1, b'not-touch')
        self.assertEqual(self.events, [('right', True), ('right', False)])

    def test_center_press_finishes_swipe_then_clicks(self):
        self.swipe_frames('right')
        self.step_feed(touch(4, 3, state=3, buttons=0x80))
        self.step_feed(touch(9, 7, state=4, buttons=0))
        expected=[('right', True), ('right', False), ('center', True), ('center', False)]
        self.assertEqual(self.events, expected)
        self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS)
        self.recognizer.tick()
        self.assertEqual(self.events, expected)
        self.assertEqual(self.recognizer.summary()['physicalClicks'], 1)

    def test_failed_direction_release_never_sends_center_or_retries(self):
        self.swipe_frames('right')
        def reject(action, down):
            self.events.append((action,down))
            return False
        self.recognizer.emit=reject
        with self.assertRaises(RuntimeError):self.step_feed(b'\x00\x80')
        self.recognizer.tick()
        self.recognizer.stop()
        self.assertEqual(self.events,[('right',True),('right',False)])
        self.assertTrue(self.recognizer.core.failed)
        self.assertEqual(self.recognizer.summary()['physicalClicks'],0)

    def test_stop_unbind_deadline_and_invalid_clock_release_known_pulse(self):
        for lifecycle in ('stop', 'unbind', 'deadline', 'invalid-clock'):
            clock = FakeClock()
            calls = []
            r = SwipeClick(lambda action, down: calls.append((action, down)),
                           self.regions, clock=clock, max_seconds=.20)
            r.bind(1)
            r.feed(1, b'\x00\x00')
            r.feed(1, touch(-80, 0, state=3))
            r.feed(1, touch(0, 0, state=4))
            r.feed(1, touch(0, 0, state=7))
            self.assertEqual(calls, [('right', True)])
            if lifecycle == 'stop':
                r.stop()
            elif lifecycle == 'unbind':
                self.assertTrue(r.unbind(1))
            elif lifecycle == 'deadline':
                clock.step(.20)
                r.tick()
            else:
                clock.now = float('nan')
                r.tick()
            self.assertEqual(calls, [('right', True), ('right', False)])
            self.assertIsNone(r.pending_swipe)

    def test_center_press_at_any_position_and_button_only_press(self):
        for x, y in ((-100, -100), (100, 100), (0, 0), (100, 0)):
            self.events.clear()
            self.step_feed(touch(x, y, state=3))
            self.step_feed(touch(x, y, state=4, buttons=0x80))
            self.step_feed(touch(x, y, state=7, buttons=0x80))
            self.step_feed(b'\x00\x00')
            self.assertEqual(self.events, [('center', True), ('center', False)])
        self.recognizer = SwipeClick(lambda action, down: self.events.append((action, down)),
                                     self.regions, clock=self.clock, max_actions=8)
        self.recognizer.bind(1)
        self.recognizer.feed(1, b'\x00\x00')
        self.events.clear()
        self.step_feed(b'\x00\x80')
        self.step_feed(b'\x00\x00')
        self.assertEqual(self.events, [('center', True), ('center', False)])

    def test_wrong_generation_unbind_does_not_release_current_pulse(self):
        self.step_feed(touch(-80,0,state=3))
        self.step_feed(touch(0,0,state=4))
        self.step_feed(touch(0,0,state=7))
        self.assertFalse(self.recognizer.unbind(99))
        self.assertEqual(self.events,[('right',True)])
        self.assertIsNotNone(self.recognizer.pending_swipe)
        self.clock.step(.061)
        self.recognizer.tick()
        self.assertEqual(self.events,[('right',True),('right',False)])

    def test_physical_press_during_contact_cancels_swipe(self):
        self.step_feed(touch(-80, 0, state=3))
        self.step_feed(touch(0, 0, state=4))
        self.step_feed(touch(0, 0, state=4, buttons=0x80))
        self.step_feed(touch(0, 0, state=7, buttons=0x80))
        self.step_feed(b'\x00\x00')
        self.assertEqual(self.events, [('center', True), ('center', False)])

    def test_press_then_slide_and_button_only_press_never_make_arrow(self):
        self.step_feed(touch(-80, 0, state=3))
        self.step_feed(touch(-80, 0, state=4, buttons=0x80))
        self.step_feed(touch(0, 0, state=4, buttons=0))
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [('center', True), ('center', False)])
        self.events.clear()
        self.step_feed(b'\x00\x80')
        self.step_feed(b'\x00\x00')
        self.assertEqual(self.events, [('center', True), ('center', False)])

    def test_long_hold_then_move_and_malformed_input_block_until_lift(self):
        self.step_feed(touch(-80, 0, state=3))
        self.step_feed(touch(0, 0, state=4), .81)
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])
        self.step_feed(touch(-80, 0, state=3))
        self.step_feed(b'not-touch')
        self.step_feed(touch(0, 0, state=4))
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])

    def test_stale_generation_cancels_and_requires_a_lift(self):
        self.step_feed(touch(-80, 0, state=3))
        self.clock.step()
        self.recognizer.feed(99, touch(0, 0, state=4))
        self.step_feed(touch(0, 0, state=4))
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])

    def test_multitouch_invalid_frames_and_reconnect_cancel(self):
        self.step_feed(touch(-80, 0))
        self.step_feed(bytes((2, 0, 0x32, 1, 0, 0)) + touch(0, 0)[6:] + touch(0, 0)[6:])
        self.step_feed(touch(0, 0, state=4))
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])
        self.step_feed(touch(-80, 0))
        self.recognizer.unbind(1)
        self.recognizer.bind(2)
        self.generation = 2
        self.step_feed(touch(0, 0, state=4))
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])

    def test_gap_long_gesture_tiny_and_diagonal_do_not_tap(self):
        self.step_feed(touch(-80, 0))
        self.step_feed(touch(0, 0, state=4), .2)
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])
        self.step_feed(touch(-80, 0))
        self.step_feed(touch(0, 0, state=4), .81)
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])
        self.step_feed(touch(-5, 0))
        self.step_feed(touch(5, 0, state=4))
        self.step_feed(touch(5, 0, state=7))
        self.assertEqual(self.events, [])
        self.step_feed(touch(-80, -80))
        self.step_feed(touch(0, 0, state=4))
        self.step_feed(touch(0, 0, state=7))
        self.assertEqual(self.events, [])

    def test_continuous_contact_over_duration_limit_stays_cancelled(self):
        self.step_feed(touch(-80, 0, state=3))
        for x in [-70] * (int(SwipeClick.MAX_GESTURE_SECONDS / .1) + 1):
            self.step_feed(touch(x, 0, state=4), .1)
        self.step_feed(touch(20, 0, state=4), .1)
        self.step_feed(touch(20, 0, state=7), .02)
        self.assertEqual(self.events, [])

    def test_exact_minimum_swipe_fraction_is_accepted(self):
        self.step_feed(touch(-80, 0, state=3))
        self.step_feed(touch(-44, 0, state=4))
        self.assertTrue(self.step_feed(touch(-44, 0, state=7)))
        self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS)
        self.recognizer.tick()
        self.assertEqual(self.events, [('right', True), ('right', False)])

    def test_repeated_lift_reports_do_not_duplicate_swipe_tap(self):
        self.step_feed(touch(-80, 0, state=3))
        self.step_feed(touch(0, 0, state=4))
        self.assertTrue(self.step_feed(touch(0, 0, state=7)))
        self.assertFalse(self.step_feed(touch(0, 0, state=7)))
        self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS)
        self.recognizer.tick()
        self.assertEqual(self.events, [('right', True), ('right', False)])

    def test_rate_limit_and_shared_action_budget(self):
        for _ in range(4):
            self.swipe('right')
        self.assertEqual(len(self.events), 8)
        self.swipe('right')
        self.assertEqual(len(self.events), 8)

    def test_sixteen_press_budget_is_shared_by_swipes_and_center(self):
        for _ in range(15):
            self.clock.step(.3)
            self.step_feed(b'\x00\x00', 0)
            self.swipe('right')
        self.step_feed(b'\x00\x80')
        self.step_feed(b'\x00\x00')
        self.swipe('left')
        summary = self.recognizer.summary()
        self.assertEqual(summary['swipes']['right'], 15)
        self.assertEqual(summary['physicalClicks'], 1)
        self.assertEqual(summary['rejectedSwipes'], 1)
        self.assertEqual(summary['safety']['pressAttempts'], 16)

    def test_uncertain_semantic_write_is_one_attempt_and_fails_closed(self):
        calls = []
        def fail(action, down):
            calls.append((action, down))
            raise OSError('uncertain')
        r = SwipeClick(fail, self.regions, clock=self.clock)
        r.bind(1)
        r.feed(1, b'\x00\x00')
        with self.assertRaises(OSError):
            r.feed(1, b'\x00\x80')
        self.assertEqual(calls, [('center', True)])
        self.assertTrue(r.core.failed)
        self.assertTrue(r.core.closed)

    def test_rejected_center_release_stays_latched_without_retry(self):
        calls = []
        def reject_up(action, down):
            calls.append((action, down))
            return not (action == 'center' and down is False)
        r = SwipeClick(reject_up, self.regions, clock=self.clock)
        r.bind(1)
        r.feed(1, b'\x00\x00')
        r.feed(1, b'\x00\x80')
        r.feed(1, b'\x00\x00')
        self.assertEqual(calls, [('center', True), ('center', False)])
        self.assertTrue(r.core.failed)
        self.assertTrue(r.core.summary()['requiresOwnDeviceDestroy'])
        self.assertTrue(r.center_down_known)
        self.assertTrue(r.core.down)
        r.tick()
        r.stop()
        self.assertEqual(calls, [('center', True), ('center', False)])

    def test_invalid_clock_values_close_without_uncaught_exceptions(self):
        for bad_value in (True, float('nan'), float('inf'), 1e300, 10 ** 1000):
            clock = FakeClock()
            events = []
            r = SwipeClick(lambda action, down: events.append((action, down)),
                           self.regions, clock=clock)
            r.bind(1)
            r.feed(1, b'\x00\x00')
            clock.now = bad_value
            self.assertFalse(r.feed(1, touch(0, 0, state=3)))
            self.assertTrue(r.core.closed)
            self.assertFalse(r.core.failed)
        with self.assertRaises(ValueError):
            SwipeClick(lambda action, down: None, self.regions,
                       clock=FakeClock(), max_seconds=10 ** 1000)
        class HugeIntClock:
            def __call__(self):
                return 10 ** 1000
        with self.assertRaises(ValueError):
            SwipeClick(lambda action, down: None, self.regions,
                       clock=HugeIntClock())
        clock = FakeClock()
        r = SwipeClick(lambda action, down: None, self.regions, clock=clock)
        r.bind(1)
        r.feed(1, b'\x00\x00')
        r.feed(1, b'\x00\x80')
        clock.now = float('nan')
        self.assertTrue(r.feed(1, b'\x00\x00'))
        self.assertEqual(r.center_down_known, False)
        self.assertTrue(r.core.closed)

    def test_clock_exception_and_nonmonotonic_values_fail_closed_safely(self):
        clock = FakeClock()
        r = SwipeClick(lambda action, down: None, self.regions, clock=clock)
        r.bind(1)
        r.feed(1, b'\x00\x00')
        clock.now = -1
        self.assertFalse(r.feed(1, b'\x00\x00'))
        self.assertTrue(r.core.closed)
        def broken_clock():
            raise RuntimeError('clock failed')
        r = SwipeClick(lambda action, down: None, self.regions, clock=FakeClock())
        r._raw_clock = broken_clock
        r.bind(1)
        self.assertFalse(r.feed(1, b'\x00\x00'))
        self.assertTrue(r.core.closed)

    def test_swipe_down_and_up_failures_are_never_retried(self):
        for fail_at in (1, 2):
            calls = []
            def fail_on_stage(action, down):
                calls.append((action, down))
                if len(calls) == fail_at:
                    raise OSError('uncertain')
            r = SwipeClick(fail_on_stage, self.regions, clock=self.clock)
            r.bind(1)
            r.feed(1, b'\x00\x00')
            r.feed(1, touch(-80, 0, state=3))
            r.feed(1, touch(0, 0, state=4))
            if fail_at == 1:
                with self.assertRaises(OSError):
                    r.feed(1, touch(0, 0, state=7))
            else:
                r.feed(1, touch(0, 0, state=7))
                self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS)
                with self.assertRaises(OSError):
                    r.tick()
            self.assertEqual(calls, [('right', True)] if fail_at == 1 else
                             [('right', True), ('right', False)])
            self.assertTrue(r.core.failed)
            self.assertTrue(r.core.closed)

    def test_rejected_swipe_release_fails_closed_and_is_not_retried(self):
        calls = []
        def reject_release(action, down):
            calls.append((action, down))
            return down
        r = SwipeClick(reject_release, self.regions, clock=self.clock)
        r.bind(1)
        r.feed(1, b'\x00\x00')
        r.feed(1, touch(-80, 0, state=3))
        r.feed(1, touch(0, 0, state=4))
        r.feed(1, touch(0, 0, state=7))
        self.clock.step(SwipeClick.SWIPE_PULSE_SECONDS)
        r.tick()
        self.assertEqual(calls, [('right', True), ('right', False)])
        self.assertTrue(r.core.failed)
        self.assertTrue(r.core.closed)
        r.tick()
        r.stop()
        self.assertEqual(calls, [('right', True), ('right', False)])

    def test_initial_active_contact_without_release_baseline_is_ignored(self):
        events = []
        r = SwipeClick(lambda action, down: events.append((action, down)),
                       self.regions, clock=self.clock)
        r.bind(1)
        r.feed(1, touch(-80, 0, state=3))
        r.feed(1, touch(0, 0, state=4))
        r.feed(1, touch(0, 0, state=7))
        self.assertEqual(events, [])

    def test_swipe_tap_then_center_press_and_initial_contact(self):
        self.events.clear()
        self.swipe('right')
        self.step_feed(b'\x00\x80')
        self.step_feed(b'\x00\x00')
        self.assertEqual(self.events, [('right', True), ('right', False),
                                       ('center', True), ('center', False)])


if __name__ == '__main__':
    unittest.main()
