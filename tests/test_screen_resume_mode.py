import math
import os
import tempfile
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from screen_resume_mode import check_mode, restore_session_mode, ScreenResumeMode
from screen_power import ScreenPowerWorker
from borrowed_mode_session import BorrowedModeSession
from borrowed_runtime_journal import BorrowedRuntimeJournal, inspect_journal
from borrowed_sustained_receive import receive_sustained
from borrowed_gatt_view import TARGET, ADAPTER
from native_mode_session import NativeModeClient
from pumping_luna_client import LunaCallError
from direct_gatt_read import HID_SERVICE, REPORT_CHAR, REPORT_REFERENCE
from output_bridge import VerifiedOutputs
from fixture_devices import MemoryDevices
from test_navigation_mode import report
from test_swipe_click import touch
from test_screen_power import Client


class ModeCheckTests(unittest.TestCase):
    def check(self, values, **kwargs):
        self.read = Mock(side_effect=values)
        self.enable = Mock(return_value=True)
        self.record = Mock(return_value=True)
        return check_mode(read=self.read, enable=self.enable, record=self.record,
                          guard=kwargs.get('guard', lambda: True))

    def test_enabled_mode_has_no_write_or_journal(self):
        self.assertFalse(self.check([1]))
        self.enable.assert_not_called()
        self.record.assert_not_called()
        self.read.assert_called_once()

    def test_stopped_mode_enabled_once_and_read_back(self):
        self.assertTrue(self.check([0, 1]))
        self.enable.assert_called_once()
        self.assertEqual(self.read.call_count, 2)
        self.assertEqual([c.args[0]['stage'] for c in self.record.call_args_list],
                         ['sensor-resume-intent', 'sensor-resume-ack'])

    def test_invalid_or_failed_read_never_enables(self):
        for value in (None, True, 2, -1, '0', TimeoutError()):
            with self.subTest(value=value), self.assertRaises((RuntimeError, TimeoutError)):
                self.check([value])
            self.enable.assert_not_called()

    def test_lost_control_after_read_never_enables(self):
        with self.assertRaises(RuntimeError):
            self.check([0], guard=Mock(side_effect=[True, False]))
        self.enable.assert_not_called()

    def test_uncertain_enable_or_readback_not_repeated_within_a_check(self):
        for enabled, value in ((False, 1), (True, 0), (True, True), (True, TimeoutError())):
            with self.subTest(enabled=enabled, value=value):
                enable = Mock(return_value=enabled)
                record = Mock(return_value=True)
                with self.assertRaises((RuntimeError, TimeoutError)):
                    check_mode(read=Mock(side_effect=[0, value]), enable=enable,
                               record=record, guard=lambda: True)
                enable.assert_called_once()
                record.assert_called_once_with({'stage': 'sensor-resume-intent'})

    def test_journal_failure_prevents_write(self):
        enable = Mock()
        with self.assertRaises(RuntimeError):
            check_mode(read=lambda: 0, enable=enable, record=lambda _: False,
                       guard=lambda: True)
        enable.assert_not_called()


class ScreenTransitionsTests(unittest.TestCase):
    def test_off_observed_just_before_turn_on_is_not_missed(self):
        screen = ScreenPowerWorker()
        screen.toggle(); screen._step(Client('Screen Off'))
        self.assertFalse(screen.blocked())
        self.assertEqual(screen.resume_sequence(), 1)

    def test_only_observed_screen_off_to_on_counts(self):
        screen = ScreenPowerWorker()
        for state, count in [('Active', 0), ('Screen Saver', 0), ('Active', 0),
                             ('Screen Off', 0), ('Screen Off', 0), ('Unknown', 0),
                             ('Active', 1), ('Active', 1), ('Screen Off', 1),
                             ('Screen Saver', 2)]:
            screen._step(Client(state))
            self.assertEqual(screen.resume_sequence(), count)

    def test_once_per_resume_and_only_after_fresh_state(self):
        now = [0.]
        screen = ScreenPowerWorker(clock=lambda: now[0])
        restore = Mock()
        recovery = ScreenResumeMode(screen, None, live=lambda: True, abort=lambda: False,
                                    clock=lambda: now[0], restore=restore)
        screen._step(Client('Screen Off')); screen._step(Client())
        now[0] = 4.
        recovery.tick(lambda: None); restore.assert_not_called()
        screen._step(Client()); screen.pending = True
        recovery.tick(lambda: None); restore.assert_not_called()
        screen.pending = False
        for _ in range(20): recovery.tick(lambda: None)
        self.assertEqual(restore.call_count, 1)
        screen._step(Client('Screen Off')); screen._step(Client())
        recovery.tick(lambda: None)
        self.assertEqual(restore.call_count, 2)

    def test_reentrant_pump_keeps_motion_gated(self):
        screen = ScreenPowerWorker()
        screen._step(Client('Screen Off')); screen._step(Client())
        observed = []
        def restore(session, *, pump, **kwargs):
            observed.append(recovery.ready)
            pump()
        recovery = ScreenResumeMode(screen, None, live=lambda: True, abort=lambda: False,
                                    clock=lambda: 0., restore=restore)
        recovery.tick(lambda: recovery.tick(lambda: None))
        self.assertEqual(observed, [False]); self.assertTrue(recovery.ready)

    def retry_scenario(self, side_effect):
        now = [0.]
        screen = ScreenPowerWorker(clock=lambda: now[0])
        screen._step(Client('Screen Off')); screen._step(Client())
        restore = Mock(side_effect=side_effect)
        recovery = ScreenResumeMode(screen, None, live=lambda: True, abort=lambda: False,
                                    clock=lambda: now[0], restore=restore)
        def advance(seconds):
            now[0] += seconds; screen._step(Client()); recovery.tick(lambda: None)
        recovery.tick(lambda: None)
        return screen, recovery, restore, advance

    def test_refused_enable_retries_later_then_recovers(self):
        refused = RuntimeError('screen-resume-enable-unconfirmed')
        _, recovery, restore, advance = self.retry_scenario([refused, refused, True])
        self.assertEqual(restore.call_count, 1); self.assertFalse(recovery.ready)
        advance(.4); self.assertEqual(restore.call_count, 1)
        advance(.1); self.assertEqual(restore.call_count, 2); self.assertFalse(recovery.ready)
        advance(.9); self.assertEqual(restore.call_count, 2)
        advance(.1); self.assertEqual(restore.call_count, 3)
        self.assertTrue(recovery.ready); self.assertFalse(recovery.failed)
        self.assertEqual(recovery.completed, 1)

    def test_retries_are_bounded_until_the_next_resume(self):
        refused = RuntimeError('screen-resume-enable-unconfirmed')
        screen, recovery, restore, advance = self.retry_scenario(lambda *_a, **_k: (_ for _ in ()).throw(refused))
        for _ in range(40): advance(.5)
        self.assertEqual(restore.call_count, 6)
        self.assertFalse(recovery.ready); self.assertFalse(recovery.failed)
        screen._step(Client('Screen Off')); advance(.5)
        self.assertEqual(restore.call_count, 7)

    def test_uncertain_transport_failure_is_never_retried(self):
        for error in (LunaCallError('timed out'), TimeoutError('LS2 read timed out')):
            with self.subTest(error=error):
                _, recovery, restore, advance = self.retry_scenario([error, True])
                for _ in range(20): advance(.5)
                self.assertEqual(restore.call_count, 1)
                self.assertTrue(recovery.failed); self.assertFalse(recovery.ready)

    def test_timeout_disconnect_or_second_screen_off_aborts(self):
        for reason in ('timeout', 'link', 'screen', 'abort'):
            with self.subTest(reason=reason):
                now = [0.]; live = [True]; aborted = [False]
                screen = ScreenPowerWorker(clock=lambda: now[0])
                screen._step(Client('Screen Off')); screen._step(Client())
                def restore(session, *, guard, **kwargs):
                    if reason == 'timeout': now[0] = 16.; screen._step(Client())
                    elif reason == 'link': live[0] = False
                    elif reason == 'abort': aborted[0] = True
                    else: screen._step(Client('Screen Off'))
                    self.assertFalse(guard())
                recovery = ScreenResumeMode(screen, None, live=lambda: live[0],
                    abort=lambda: aborted[0], clock=lambda: now[0], restore=restore)
                if reason in ('link', 'abort'):
                    with self.assertRaises(RuntimeError): recovery.tick(lambda: None)
                else:
                    recovery.tick(lambda: None)
                self.assertEqual(recovery.failed, reason in ('link', 'abort'))
                self.assertFalse(recovery.ready); self.assertEqual(recovery.completed, 0)


class FakeModeApi:
    """Fake transport only: real request budgets, identity and mode decoders run."""
    def __init__(self, mode=0):
        self.mode = mode; self.calls = []; self.pumping = lambda: None
        self.intervals = []
        self.wrong_identity = False
        self.stale_readback = False
        self.refuse_enables = 0

    def call(self, client, method, params, timeout):
        method, _, _ = client._validate_request(method, params, timeout)
        if not client.guard(): raise RuntimeError('lost control')
        self.calls.append((method, params))
        self.intervals.append(getattr(client.pump, 'poll_interval', None))
        self.pumping(); client.pump()
        if not client.guard(): raise RuntimeError('lost control')
        reply = {'returnValue': True, 'address': '00:00:00:00:00:00' if self.wrong_identity else TARGET,
                 'adapterAddress': ADAPTER, 'clientId': client.client_id}
        if method == 'hid/internal/setReport':
            if params['reportData'] == [240, 160, 1]:
                if self.refuse_enables:
                    self.refuse_enables -= 1
                    return {'returnValue': False, 'errorCode': 101, 'errorText': 'refused'}
                self.mode = 1
        elif method == 'gatt/getServices':
            reply['services'] = [{'service': HID_SERVICE, 'characteristics': [
                {'characteristic': REPORT_CHAR, 'instanceId': '29', 'descriptors': [
                    {'descriptor': REPORT_REFERENCE, 'instanceId': '30'}]}]}]
        elif method == 'gatt/readDescriptorValues':
            reply['values'] = [{'descriptor': REPORT_REFERENCE, 'instanceId': '30',
                                'value': {'bytes': [240, 3]}}]
        elif method == 'gatt/readCharacteristicValues':
            reply['values'] = [{'characteristic': REPORT_CHAR, 'instanceId': '29',
                                'value': {'bytes': [160, 0 if self.stale_readback and self.enables() else self.mode]}}]
        else: raise AssertionError(method)
        return reply

    def patch(self):
        return patch.object(NativeModeClient, '_call_serialized',
                            lambda client, method, params, timeout: self.call(client, method, params, timeout))

    def enables(self):
        return sum(params.get('reportData') == [240, 160, 1] for _, params in self.calls)


def session(record=lambda _: True):
    value = BorrowedModeSession(SimpleNamespace(generation=7, client_id='5', close=lambda: None),
        read_mode=lambda: 0, read_stop_mode=lambda: 0, write_mode=lambda _: True,
        control_valid=lambda: True, record=record)
    value.state = 'active'; value.enable_attempted = True
    return value


class ProtocolTests(unittest.TestCase):
    def test_original_session_retains_final_stop_responsibility(self):
        api = FakeModeApi()
        events = []; writes = []
        def write(mode):
            writes.append(mode); api.mode = mode; return True
        current = session(lambda e: events.append(e['stage']) or True)
        current.state = 'new'; current.enable_attempted = False
        current.read_mode = current.read_stop_mode = lambda: api.mode
        current.write_mode = write
        current.start()
        with api.patch():
            for _ in range(3):
                api.mode = 0
                restore_session_mode(current, pump=lambda: None, guard=lambda: True)
        self.assertEqual(writes, [1])
        self.assertTrue(current.stop()['modeZeroVerified'])
        self.assertEqual(writes, [1, 0])
        self.assertEqual(events[-2:], ['sensor-stop-intent', 'sensor-zero-confirmed'])

    def test_stopped_mode_on_existing_client(self):
        api = FakeModeApi(); events = []
        with api.patch():
            self.assertTrue(restore_session_mode(session(lambda e: events.append(e) or True),
                                                 pump=lambda: None, guard=lambda: True))
        self.assertEqual(api.enables(), 1)
        self.assertEqual([m for m, _ in api.calls], ['hid/internal/setReport', 'gatt/getServices',
            'gatt/readDescriptorValues', 'gatt/readCharacteristicValues', 'hid/internal/setReport', 'gatt/readCharacteristicValues'])
        self.assertTrue(all(p.get('clientId', '5') == '5' for _, p in api.calls))

    def test_enabled_mode_only_selects_and_reads(self):
        api = FakeModeApi(1)
        with api.patch():
            self.assertFalse(restore_session_mode(session(), pump=lambda: None, guard=lambda: True))
        self.assertEqual(api.enables(), 0)
        self.assertEqual([p['reportData'] for _, p in api.calls if 'reportData' in p], [[240, 240, 160]])

    def test_multiple_resumes_each_get_fresh_bounded_check(self):
        api = FakeModeApi(); current = session()
        with api.patch():
            for _ in range(3):
                api.mode = 0
                self.assertTrue(restore_session_mode(current, pump=lambda: None, guard=lambda: True))
        self.assertEqual(api.enables(), 3)

    def test_foreign_reply_never_enables(self):
        api = FakeModeApi(); api.wrong_identity = True
        with api.patch(), self.assertRaises(RuntimeError):
            restore_session_mode(session(), pump=lambda: None, guard=lambda: True)
        self.assertEqual(api.enables(), 0)


class JournalTests(unittest.TestCase):
    def test_repeated_resumes_keep_cleanup_and_crash_recovery_valid(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted), tempfile.TemporaryDirectory() as directory:
                os.chmod(directory, 0o770)
                run = 'a' * 32
                journal = BorrowedRuntimeJournal(directory, run, state_uid=os.getuid(), group=os.getgid())
                try:
                    journal({'stage': 'gatt-lookup-intent', 'generation': 7})
                    journal({'stage': 'borrowed-view-obtained', 'generation': 7,
                             'ownership': 'unproven', 'clientIdSha256': 'a' * 64})
                    journal({'stage': 'sensor-enable-intent'}); journal({'stage': 'sensor-enable-ack'})
                    for _ in range(3):
                        journal({'stage': 'sensor-resume-intent'}); journal({'stage': 'sensor-resume-ack'})
                    if interrupted: journal({'stage': 'sensor-resume-intent'})
                    def inspect():
                        return inspect_journal(directory, run, owner_uid=os.getuid(),
                                               state_uid=os.getuid(), group=os.getgid())['status']
                    self.assertEqual(inspect(), 'sensor-state-unknown')
                    journal({'stage': 'sensor-stop-intent'}); journal({'stage': 'sensor-zero-confirmed'})
                    self.assertEqual(inspect(), 'zero-recorded-live-recheck-required')
                finally: journal.close()


class ReceiveIntegrationTests(unittest.TestCase):
    def scenario(self, *, early=False, drop_mode=True, stale_readback=False, refused=0):
        now = [0.]; queue = deque(); phase = [0]; next_frame = [0.]
        device = MemoryDevices()
        outputs = VerifiedOutputs(1, 2, ioctl_fn=device.ioctl, write_fn=device.write, sleep_fn=lambda _: None)
        screen = ScreenPowerWorker(clock=lambda: now[0]); tv = Client(); screen._step(tv)
        api = FakeModeApi(1); api.stale_readback = stale_readback; during = []; events = []
        api.refuse_enables = refused
        def advance(delta):
            now[0] += delta
            if phase[0] == 0 and now[0] >= .4:
                phase[0] = 1; tv.state = 'Screen Off'
                if drop_mode: api.mode = 0
            if phase[0] == 1 and now[0] >= .8:
                phase[0] = 2; tv.state = 'Active'
                queue.append(b'\xfc\0\0')
                for value in (touch(-1500, -200, state=3), touch(-1000, -200, state=4), touch(-1000, -200, state=7)):
                    queue.append(b'\xfc'+value)
                queue.extend((b'\xfc\0\x80', b'\xfc\0\0'))
            screen._step(tv)
        def read(fd, size):
            if queue: return queue.popleft()
            if api.mode == 1 and now[0] >= next_frame[0]:
                next_frame[0] = now[0] + .009
                return report(.15 * math.sin(max(0, now[0] - .15) * 21))  # side-to-side shake: turns around every ~0.15 s
            raise BlockingIOError()
        def pump():
            during.append(outputs.motion_writes); advance(.02)
        api.pumping = pump
        current = session(lambda e: events.append(e) or True)
        options = {'system_key_emit': lambda _: True, 'screen_control': screen}
        if early:
            from early_navigation import EarlyNavigation
            prepared = EarlyNavigation(outputs, 8, generation=7, guard=lambda: True,
                abort=lambda: False, clock=lambda: now[0], read_fn=read,
                system_key_emit=lambda _: True, screen_control=screen)
            prepared.start(); options = {'prepared_receiver': prepared}
        stats = {}
        with api.patch(), patch('cursor_visibility_probe.start', return_value=None):
            result = receive_sustained(current, outputs, 8, duration=None, abort=lambda: now[0] >= 2. + refused,
                clock=lambda: now[0], read_fn=read, sleep_fn=advance, stats=stats, **options)
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(outputs.verify_released())
        self.assertEqual(set(api.intervals), {.005})
        if stale_readback:
            self.assertGreater(api.enables(), 1)
            self.assertEqual(outputs.motion_writes, during[-1])
        else:
            self.assertEqual(api.enables(), int(drop_mode) + refused)
            self.assertGreater(outputs.motion_writes, during[-1])
        self.assertEqual(len(set(during)), 1)
        keys = [(kind, code, value) for _, batch in device.writes for _, _, kind, code, value in batch]
        self.assertIn((1, 106, 1), keys); self.assertIn((1, 28, 1), keys)
        stages = ['sensor-resume-intent'] * api.enables()
        if drop_mode and not stale_readback: stages.append('sensor-resume-ack')
        self.assertEqual([e['stage'] for e in events], stages)

    def test_sensor_stops_during_screen_off_then_motion_and_navigation_recover(self):
        self.scenario()

    def test_failed_mode_readback_keeps_navigation_alive_and_motion_gated(self):
        self.scenario(stale_readback=True)

    def test_enable_refused_just_after_resume_recovers_on_retry(self):
        self.scenario(refused=1)

    def test_already_enabled_does_not_restart_sensor(self):
        self.scenario(drop_mode=False)

    def test_bundled_early_navigation_path_also_recovers(self):
        self.scenario(early=True)


if __name__ == '__main__': unittest.main()
