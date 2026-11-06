"""Exercise native reply callbacks without a TV or feature writes."""
import ctypes as C
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/native'))
from native_luna import Error, Luna


class Tests(unittest.TestCase):
    def bus(self, raw):
        bus = Luna()
        bus.failed = False
        bus.callbacks = []
        bus.handle = C.c_void_p(1)
        bus.context = object()
        bus.error = Error()
        bus.callback_type = lambda fn: fn
        bus.payload = lambda message: raw
        pending = []
        def call(handle, uri, params, callback, data, token, error):
            pending.append(callback)
            return True
        bus.call = Mock(side_effect=call)
        bus.iterate = lambda *_: pending.pop(0)(None, None, None)
        return bus

    def test_large_device_inventory_is_accepted_once(self):
        value = {'returnValue': True, 'devices': [{'name': 'x' * 300} for _ in range(300)]}
        raw = json.dumps(value).encode()
        self.assertGreater(len(raw), 65536)
        bus = self.bus(raw)
        with patch('native_luna.time.sleep'):
            self.assertEqual(bus('device/getStatus', {'subscribe': False}, 5), value)
        self.assertEqual(bus.call.call_count, 1)
        self.assertFalse(bus.failed)

    def test_oversize_and_malformed_responses_fail_without_repeating(self):
        for method, raw in (
            ('device/getStatus', b' ' * 1048577),
            ('adapter/getStatus', json.dumps({'data': 'x' * 65536}).encode()),
            ('device/getStatus', b'not json'),
            ('device/getStatus', None),
        ):
            with self.subTest(method=method, size=None if raw is None else len(raw)):
                bus = self.bus(raw)
                with patch('native_luna.time.sleep'):
                    with self.assertRaises(RuntimeError): bus(method, {}, 5)
                    with self.assertRaises(RuntimeError): bus(method, {}, 5)
                self.assertEqual(bus.call.call_count, 1)
                self.assertTrue(bus.failed)


if __name__ == '__main__': unittest.main()
