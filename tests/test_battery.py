import sys
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/native'), str(ROOT / 'src/runtime')]
import battery_status as battery
from battery_read import ScreenRefresh
from runtime_device import identity


def reply():
    device = identity()
    return {'returnValue': True, 'address': device.remote, 'adapterAddress': device.adapter, 'service': battery.SERVICE,
            'values': [{'characteristic': battery.LEVEL, 'value': {'bytes': [75]}},
                       {'characteristic': '00002a1a-0000-1000-8000-00805f9b34fb', 'value': {'bytes': []}}]}


class BatteryTests(unittest.TestCase):
    def test_rejects_other_devices_and_malformed_percentages(self):
        device = identity()
        def parse(value): return battery.percentage(value, device.remote, device.adapter, '5')
        self.assertEqual(parse(reply()), 75)
        for key, value in [('address', 'wrong'), ('adapterAddress', 'wrong'), ('service', 'wrong'), ('clientId', '6'), ('returnValue', False)]:
            data = reply(); data[key] = value
            with self.assertRaises(ValueError): parse(data)
        for value in ([101], [-1], [True], ['75'], [], [75, 80]):
            data = reply(); data['values'][0]['value']['bytes'] = value
            with self.assertRaises(ValueError): parse(data)
        data = reply(); data['values'] *= 2
        with self.assertRaises(ValueError): parse(data)

    def test_display_hides_age_and_never_uses_a_different_remote(self):
        with tempfile.TemporaryDirectory() as state:
            battery.save(state, 'remote', 'adapter', 0, now=lambda: 1000)
            self.assertEqual('Battery: 0%', battery.label(state, 'remote', 'adapter', now=lambda: 1030))
            self.assertEqual('Battery: 0%', battery.label(state, 'remote', 'adapter', now=lambda: 1901))
            self.assertIn('unavailable', battery.label(state, 'other', 'adapter', now=lambda: 1030))
            self.assertIn('unavailable', battery.label(state, 'remote', 'adapter', now=lambda: 999))
            (Path(state) / 'battery.json').chmod(0o666)
            self.assertIn('unavailable', battery.label(state, 'remote', 'adapter', now=lambda: 1030))

    def test_each_screen_open_uses_only_its_own_reply_and_never_a_late_reply(self):
        from battery_status import ScreenReading
        with tempfile.TemporaryDirectory() as state:
            r, w = os.pipe()
            with os.fdopen(w, 'wb', buffering=0) as stream:
                worker = Mock(); worker.poll.return_value = None; worker.stdin = stream
                clock = [10]
                display = ScreenReading(state, clock=lambda: clock[0])
                battery.save(state, 'remote', 'adapter', 75)
                display.refresh(worker); first = os.read(r, 100).decode().strip()
                self.assertEqual(display.text('remote', 'adapter'), 'Battery: reading...')
                battery.save(state, 'remote', 'adapter', 74, request_id=first)
                self.assertEqual(display.text('remote', 'adapter'), 'Battery: 74%')
                display.refresh(worker); second = os.read(r, 100).decode().strip()
                self.assertNotEqual(first, second)
                self.assertEqual(display.text('remote', 'adapter'), 'Battery: reading...')
                clock[0] = 17
                self.assertEqual(display.text('remote', 'adapter'), 'Battery: unavailable')
                battery.save(state, 'remote', 'adapter', 73, request_id=second)
                self.assertEqual(display.text('remote', 'adapter'), 'Battery: unavailable')
                display.refresh(None)
                self.assertEqual(display.text('remote', 'adapter'), 'Battery: unavailable')
            os.close(r)

    def test_refresh_is_nonblocking_and_loss_of_link_discards_async_reply(self):
        device = identity()
        for lost in (False, True):
            with tempfile.TemporaryDirectory() as state:
                r, w = os.pipe(); out_r, out_w = os.pipe()
                child = Mock(); child.stdout = os.fdopen(out_r, 'rb', buffering=0); child.poll.return_value = None
                child.wait.return_value = 0
                child.kill.side_effect = lambda: setattr(child.poll, 'return_value', 0)
                spawn = Mock(return_value=child); link = [True]
                refresh = ScreenRefresh('5', lambda: link[0], fd=r, state=state, spawn=spawn)
                try:
                    refresh.tick()
                    spawn.assert_not_called()  # Reception alone never requests battery I/O.
                    nonce = 'a' * 32
                    with patch('native_app_identity.verify_self', return_value=True):
                        os.write(w, (nonce + '\n').encode()); refresh.tick()
                        self.assertEqual(spawn.call_count, 1)
                        self.assertFalse((Path(state) / 'battery.json').exists())
                        refresh.tick()
                        self.assertEqual(spawn.call_count, 1)
                        os.write(out_w, json.dumps(reply()).encode()); link[0] = not lost
                        refresh.tick()
                    self.assertEqual(battery.label(state, device.remote, device.adapter, request_id=nonce),
                                     'Battery: unavailable' if lost else 'Battery: 75%')
                    self.assertIn('gatt/readCharacteristicValues', spawn.call_args.args[0][-2])
                finally:
                    refresh.close(); os.close(r); os.close(w); os.close(out_w)


if __name__ == '__main__': unittest.main()
