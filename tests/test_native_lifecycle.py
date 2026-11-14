"""Own-application lifecycle and bounded control requests without a TV."""
import ctypes as C
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/integrated'), str(ROOT / 'src/native')]
from native_bus import NativeBus, lifecycle_event
from native_luna import Error
from graphics import Canvas


class NativeLifecycleTests(unittest.TestCase):
    def test_tv_and_ose_event_fields_are_normalized(self):
        self.assertEqual(lifecycle_event({'returnValue': True, 'message': 'registered'}), ('registered', {}))
        params = {'displayAffinity': 0}
        self.assertEqual(lifecycle_event({'returnValue': True, 'message': 'relaunch', 'parameters': params}), ('relaunch', params))
        self.assertEqual(lifecycle_event({'returnValue': True, 'event': 'close'}), ('close', {}))
        for value in ({'returnValue': False}, {'returnValue': True, 'message': 'unknown'},
                      {'returnValue': True, 'message': 'relaunch', 'parameters': []}):
            with self.assertRaises((ValueError, RuntimeError)):
                lifecycle_event(value)

    def window(self):
        window = Canvas.__new__(Canvas)
        window.window = 123; window.sdl = object(); window.renderer = 456
        window.show_pending = True; window.restore_pending = False
        calls = []
        window.bind = lambda lib, name, result, args: lambda handle: calls.append((name, handle))
        window.present_frame = lambda handle: calls.append(('present', handle))
        return window, calls

    def test_initial_window_revealed_only_when_frame_is_ready(self):
        window, calls = self.window()
        self.assertEqual(calls, [])
        window.present()
        self.assertEqual(calls, [('SDL_ShowWindow', 123), ('present', 456), ('SDL_RaiseWindow', 123)])
        calls.clear(); window.present()
        self.assertEqual(calls, [('present', 456)])

    def test_relaunch_does_not_expose_old_frame_before_draw(self):
        window, calls = self.window()
        window.show_pending = False
        window.minimize(); window.restore()
        self.assertEqual(calls, [('SDL_MinimizeWindow', 123)])
        window.present()
        self.assertEqual(calls[1:], [('SDL_RestoreWindow', 123), ('SDL_ShowWindow', 123),
                                   ('present', 456), ('SDL_RaiseWindow', 123)])

    def run_background(self, reopen, started_at=None):
        import native_manager as manager
        from contextlib import ExitStack
        app = MagicMock()
        app.reset = app.pairing = app.infrared = None
        app.saving_assignments = app.stop_requested = app.done = False
        app.values = {'remoteAddress': '', 'adapterAddress': ''}
        worker = MagicMock()
        iteration = [0]
        worker.poll.side_effect = lambda: 0 if iteration[0] >= 3 else None
        bus = MagicMock()
        bus.__enter__.return_value = bus
        def events():
            iteration[0] += 1
            if iteration[0] == 2 and reopen: return [('relaunch', {'inputHandoff':'a'*32} if reopen == 'internal' else {})]
            return []
        bus.events.side_effect = events
        # A finished hidden receiver must exit to allow a fresh input-device jail.
        # A manually opened settings window instead survives until the user closes it.
        app.handle.side_effect = lambda *_: setattr(app, 'done', True)
        canvas = MagicMock()
        canvas.events.side_effect = lambda: [('close', None)] if iteration[0] >= 3 else []
        with ExitStack() as stack:
            for name, value in [('NativeBus', bus), ('RuntimeSetup', app), ('pending_worker', True),
                                ('Canvas', canvas), ('subprocess.Popen', worker)]:
                stack.enter_context(patch.object(manager, name, return_value=value) if '.' not in name
                                    else patch('native_manager.' + name, return_value=value))
            status = stack.enter_context(patch.object(manager, 'write_status'))
            stack.enter_context(patch('native_manager.time.monotonic', side_effect=[100.1,100.2,100.3,100.4,100.5,100.6]))
            stack.enter_context(patch('native_manager.signal.signal'))
            stack.enter_context(patch('native_manager.time.sleep'))
            stack.enter_context(patch('native_manager.os.set_blocking'))
            stack.enter_context(patch('native_manager.os.open', return_value=123))
            stack.enter_context(patch('native_manager.os.close'))
            stack.enter_context(patch('native_manager.os.read', side_effect=BlockingIOError))
            factory = manager.Canvas
            manager.main(started_at=started_at)
            self.assertEqual(factory.call_count, 1 if reopen is True else 0)
            # Instrumentation must not add another write or change lifecycle.
            worker_status = [call for call in status.call_args_list if call.args[0] == 'native-status.json']
            self.assertEqual(len(worker_status), 2)
            initial = worker_status[0].args[1]
            self.assertEqual(initial['status'], 'worker-starting')
            timings = initial['startupSteps']
            self.assertEqual(list(timings), ['importsReadyMs','busReadyMs','settingsLoadedMs','handoffCheckedMs','workerSpawnedMs'])
            self.assertEqual(list(timings.values()), sorted(timings.values()))
        if reopen is True:
            self.assertTrue(app.draw.called)
            self.assertTrue(all(call.args == (canvas,) for call in app.draw.call_args_list))
            app.battery.refresh.assert_called_once_with(worker)
        else:
            app.draw.assert_not_called()
            app.battery.refresh.assert_not_called()
            app.battery.text.assert_not_called()
        worker.terminate.assert_not_called()
        return timings

    def test_internal_launch_retry_does_not_show_settings_or_start_another_worker(self):
        self.run_background('internal')

    def test_background_timing_keeps_wrapper_import_baseline(self):
        timings = self.run_background(False, started_at=99.)
        self.assertEqual(timings['importsReadyMs'],1100)
        self.assertEqual(timings['workerSpawnedMs'],1500)

    def test_background_receiver_never_creates_settings_window(self):
        self.run_background(False)

    def test_user_relaunch_opens_settings_during_background_reception(self):
        self.run_background(True)

    def bus(self):
        bus = NativeBus()
        bus.handle = C.c_void_p(1); bus.error = Error()
        bus.callback_type = lambda fn: fn
        bus.decode = lambda message: {'returnValue': True}
        calls = []
        pending = []
        def once(handle, uri, raw, callback, data, token, error):
            calls.append((uri, raw)); pending.append(callback); return True
        bus.once = once
        bus.pump = lambda: pending.pop(0)(None, None, None)
        return bus, calls

    def test_requests_use_only_own_service_and_do_not_retain_completed_callbacks(self):
        bus, calls = self.bus()
        for _ in range(100):
            self.assertEqual(bus.request('status', {}), {'returnValue': True})
            self.assertEqual(bus.callbacks, [])
        self.assertTrue(all(row == (b'luna://org.magicsirimote.app.service/status', b'{}') for row in calls))
        with self.assertRaises(ValueError):
            bus.request('luna://another.service/change', {})
        with self.assertRaises(ValueError):
            bus.request('configure', {'data': 'x' * 8192})
        self.assertEqual(len(calls), 100)

    def test_unknown_outcome_is_not_repeated_and_callback_survives_until_close(self):
        bus, calls = self.bus()
        with patch('native_bus.time.monotonic', side_effect=[0, 20]):
            with self.assertRaises(RuntimeError):
                bus.request('start', {})
        self.assertFalse(bus.failed)
        self.assertTrue(bus.request_failed)
        self.assertEqual(len(bus.callbacks), 1)
        with self.assertRaises(RuntimeError):
            bus.request('start', {})
        self.assertEqual(len(calls), 1)

    def test_status_timeout_keeps_lifecycle_alive_and_manual_read_retry_works(self):
        bus,calls=self.bus()
        with patch('native_bus.time.monotonic',side_effect=[0,20]):
            with self.assertRaisesRegex(RuntimeError,'status service did not respond'):
                bus.request('status',{})
        self.assertFalse(bus.failed);self.assertFalse(bus.request_failed)
        bus.context=C.c_void_p(1);bus.iterate=Mock(return_value=0)
        NativeBus.pump(bus)  # This previously raised and terminated the TV window.
        self.assertEqual(len(calls),1)
        # The late reply from the timed-out read must not satisfy a new request.
        self.assertEqual(bus.request('status',{}),{'returnValue':True})
        self.assertEqual(len(calls),2)

    def test_uncertain_mutation_keeps_close_and_status_available_but_blocks_writes(self):
        bus,calls=self.bus()
        with patch('native_bus.time.monotonic',side_effect=[0,20]):
            with self.assertRaises(RuntimeError):bus.request('reset',{})
        bus.context=C.c_void_p(1);bus.iterate=Mock(return_value=0)
        NativeBus.pump(bus)
        with self.assertRaises(RuntimeError):bus.request('start',{})
        self.assertEqual(bus.request('status',{}),{'returnValue':True})
        self.assertEqual(bus.show_home(),{'returnValue':True})
        self.assertEqual(len(calls),3)

    def test_repeated_missing_read_replies_are_bounded(self):
        bus,calls=self.bus();bus.callbacks=[object()]*64
        with self.assertRaisesRegex(RuntimeError,'Too many unanswered'):
            bus.request('status',{})
        self.assertFalse(calls);self.assertFalse(bus.failed)

    def test_failed_startup_cancel_uses_one_exact_activity_id(self):
        import json
        bus, calls = self.bus(); bus.cancel_startup(271)
        self.assertEqual(calls[0][0], b'luna://com.webos.service.activitymanager/cancel')
        self.assertEqual(json.loads(calls[0][1]), {'activityId':271})
        for invalid in (0, -1, True, '271'):
            with self.assertRaises(ValueError): bus.cancel_startup(invalid)
        self.assertEqual(len(calls), 1)

    def test_startup_activity_is_persistent_and_calls_only_own_service(self):
        import json
        bus, calls = self.bus()
        bus.create_startup('a' * 48)
        uri, raw = calls[0]
        value = json.loads(raw)
        self.assertEqual(uri, b'luna://com.webos.service.activitymanager/create')
        self.assertIs(value['replace'], False)
        self.assertIs(value['activity']['type']['persist'], True)
        self.assertIs(value['activity']['type']['immediate'], True)
        self.assertEqual(value['activity']['type']['priority'], 'highest')
        self.assertNotIn('foreground', value['activity']['type'])
        self.assertNotIn('background', value['activity']['type'])
        self.assertEqual(value['activity']['name'], 'org.magicsirimote.app.startup')
        self.assertEqual(value['activity']['callback']['method'], 'luna://org.magicsirimote.app.service/startupTick')
        with self.assertRaises(ValueError): bus.create_startup('invalid')


if __name__ == '__main__':
    unittest.main()
