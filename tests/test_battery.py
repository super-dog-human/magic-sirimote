import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/native'), str(ROOT / 'src/runtime')]
import battery_status as battery
from battery_read import capture, BatteryClient
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

    def test_one_shot_read_cannot_write_connect_or_repeat(self):
        for method in ('gatt/connect', 'gatt/discoverServices', 'gatt/writeCharacteristicValue'):
            call = BatteryClient('5', pump=lambda: None, guard=lambda: True)
            with self.assertRaises(ValueError): call._validate_request(method, call.params, 2)
        call = BatteryClient('5', pump=lambda: None, guard=lambda: True)
        self.assertEqual(call._validate_request('gatt/readCharacteristicValues', call.params, 2), ('gatt/readCharacteristicValues', 2, False))
        with self.assertRaises(ValueError): call._validate_request('gatt/readCharacteristicValues', call.params, 2)

    def test_lost_link_discards_reply_and_failed_read_replaces_old_value(self):
        device = identity()
        with tempfile.TemporaryDirectory() as state:
            battery.save(state, device.remote, device.adapter, 75)
            factory = Mock(return_value=Mock(return_value=reply()))
            guard = Mock(side_effect=[True, False])
            self.assertIsNone(capture('5', pump=lambda: None, guard=guard, client_factory=factory, state=state))
            self.assertIn('unavailable', battery.label(state, device.remote, device.adapter))
            factory = Mock(return_value=Mock(side_effect=TimeoutError))
            self.assertIsNone(capture('5', pump=lambda: None, guard=lambda: True, client_factory=factory, state=state))
            factory.return_value.assert_called_once()

    def test_unavailable_link_never_dispatches(self):
        with tempfile.TemporaryDirectory() as state:
            factory = Mock()
            capture('5', pump=lambda: None, guard=lambda: False, client_factory=factory, state=state)
            factory.assert_not_called()

    def test_display_marks_age_and_never_uses_a_different_remote(self):
        with tempfile.TemporaryDirectory() as state:
            battery.save(state, 'remote', 'adapter', 0, now=lambda: 1000)
            self.assertIn('0% (last read', battery.label(state, 'remote', 'adapter', now=lambda: 1030))
            self.assertIn('may have changed', battery.label(state, 'remote', 'adapter', now=lambda: 1901))
            self.assertIn('unavailable', battery.label(state, 'other', 'adapter', now=lambda: 1030))
            self.assertIn('unavailable', battery.label(state, 'remote', 'adapter', now=lambda: 999))
            (Path(state) / 'battery.json').chmod(0o666)
            self.assertIn('unavailable', battery.label(state, 'remote', 'adapter', now=lambda: 1030))


if __name__ == '__main__': unittest.main()
