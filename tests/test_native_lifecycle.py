"""Own-application lifecycle and bounded control requests without a TV."""
import ctypes as C
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_relaunch_restores_then_shows_then_raises(self):
        window = Canvas.__new__(Canvas)
        window.window = 123; window.sdl = object()
        calls = []
        window.bind = lambda lib, name, result, args: lambda handle: calls.append((name, handle))
        window.minimize(); window.restore()
        self.assertEqual(calls, [(name, 123) for name in ('SDL_MinimizeWindow', 'SDL_RestoreWindow', 'SDL_ShowWindow', 'SDL_RaiseWindow')])

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
        self.assertTrue(bus.failed)
        self.assertEqual(len(bus.callbacks), 1)
        with self.assertRaises(RuntimeError):
            bus.request('start', {})
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
        self.assertEqual(value['activity']['name'], 'org.magicsirimote.app.startup')
        self.assertEqual(value['activity']['callback']['method'], 'luna://org.magicsirimote.app.service/startupTick')
        with self.assertRaises(ValueError): bus.create_startup('invalid')


if __name__ == '__main__':
    unittest.main()
