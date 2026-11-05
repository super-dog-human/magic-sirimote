import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/runtime'))
from recovery_lookup_handoff import RecoveredLookup
from borrowed_gatt_view import TARGET, ADAPTER
from postconnect_supervisor_cycle import SupervisorCycle


def reply():
    return {'returnValue': True, 'address': TARGET, 'adapterAddress': ADAPTER, 'clientId': '5'}


class RecoveredLookupTests(unittest.TestCase):
    def setUp(self):
        self.now = 10
        self.cache = RecoveredLookup(clock=lambda: self.now)
        self.watch = Mock()
        self.watch.is_open.return_value = True
        self.watch.snapshot.return_value = {'generation': 8}
        self.lease = Mock()
        self.lease.held.return_value = True

    def remember(self):
        self.cache.remember(reply(), watch=self.watch, lease=self.lease, generation=8)

    def take(self):
        return self.cache.take(watch=self.watch, lease=self.lease)

    def test_same_live_connection_transfers_once_and_detaches_reply(self):
        original = reply()
        self.cache.remember(original, watch=self.watch, lease=self.lease, generation=8)
        original['clientId'] = '99'
        self.assertEqual(self.take(), (reply(), 8))
        self.assertIsNone(self.take())

    def test_reconnect_closed_watch_stale_snapshot_and_lost_lease_discard(self):
        for kind in ('generation', 'closed', 'stale', 'lease', 'age', 'clock', 'watch-replaced', 'lease-replaced'):
            with self.subTest(kind=kind):
                self.setUp(); self.remember()
                if kind == 'generation': self.watch.snapshot.return_value = {'generation': 9}
                elif kind == 'closed': self.watch.is_open.return_value = False
                elif kind == 'stale': self.watch.snapshot.return_value = None
                elif kind == 'lease': self.lease.held.return_value = False
                elif kind == 'age': self.now = 16
                elif kind == 'clock': self.now = 9
                elif kind == 'watch-replaced':
                    original = self.watch; self.watch = Mock()
                    self.watch.snapshot.return_value = original.snapshot.return_value
                    self.watch.is_open.return_value = True
                elif kind == 'lease-replaced':
                    self.lease = Mock(); self.lease.held.return_value = True
                self.assertIsNone(self.take())
                self.assertIsNone(self.cache.value)

    def test_invalid_or_unconfirmed_client_is_not_remembered(self):
        with self.assertRaises(ValueError):
            self.cache.remember({**reply(), 'address': 'wrong'}, watch=self.watch, lease=self.lease, generation=8)
        self.watch.snapshot.return_value = {'generation': 9}
        self.remember(); self.assertIsNone(self.take())

    def test_cycle_skips_only_the_duplicate_lookup_not_input_or_launch(self):
        self.remember()
        for changed in (False, True):
            with self.subTest(changed=changed):
                self.watch.snapshot.return_value = {'generation': 8}
                self.remember()
                if changed: self.watch.snapshot.return_value = {'generation': 9}
                cycle = SupervisorCycle.__new__(SupervisorCycle)
                cycle.watch = self.watch; cycle.lease = self.lease; cycle.lookup_cache = self.cache
                cycle.receiver_app = 'app'; cycle.receiver_package = 'pkg'; cycle.pin = {}
                cycle.intent = Mock(return_value=True); cycle.run = 'a' * 32
                cycle.receiver_state = 'unused'; cycle.controller_state = Path('unused')
                cycle.controller_process = {}; cycle.clock = lambda: 10
                cycle.write_start = Mock(return_value=True); cycle.write_request = Mock(return_value=True)
                with patch('runtime_bundle.active', return_value=False), patch('receiver_package_attestation.package_matches', return_value=True), patch('prelaunch_handoff_runtime.lookup_before_input', return_value=(reply(), 9)) as lookup, patch('prelaunch_handoff_runtime.write_json_once') as record, patch('prelaunch_handoff_runtime.PrelaunchOwner') as owner:
                    result = cycle.begin()
                    self.assertEqual(result['status'], 'accepted')
                    self.assertEqual(lookup.call_count, int(changed))
                    owner.return_value.begin.assert_called_once()
                    cycle.write_request.assert_called_once()
                    if not changed:
                        self.assertEqual(record.call_args.args[1]['generation'], 8)
                        self.assertTrue(str(record.call_args.args[0]).endswith('-reused.json'))


if __name__ == '__main__':
    unittest.main()
