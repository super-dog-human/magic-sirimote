import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/runtime'))
from postconnect_supervisor_cycle import SupervisorCycle
from borrowed_gatt_requester import revalidate_client
from borrowed_gatt_view import TARGET, ADAPTER
from pumping_luna_client import LunaChildStopError


class StartupReadinessTests(unittest.TestCase):
    def cycle(self):
        cycle = SupervisorCycle.__new__(SupervisorCycle)
        cycle.watch = Mock(); cycle.watch.snapshot.return_value = {'generation': 8}
        cycle.lease = Mock(); cycle.lease.held.return_value = True
        cycle.lookup_cache = None
        cycle.receiver_app = 'app'; cycle.receiver_package = 'pkg'; cycle.pin = {}
        cycle.intent = Mock(return_value=True); cycle.run = 'a' * 32
        cycle.receiver_state = 'unused'; cycle.controller_state = Path('unused')
        cycle.controller_process = {}; cycle.clock = lambda: 10
        cycle.write_start = Mock(return_value=True); cycle.write_request = Mock(return_value=True)
        return cycle

    def test_startup_uses_verified_read_without_skipping_handoff(self):
        for bundled in (True, False):
            with self.subTest(bundled=bundled):
                cycle = self.cycle()
                reply = {'returnValue': True, 'address': TARGET, 'adapterAddress': ADAPTER, 'clientId': '5'}
                with patch('runtime_bundle.active', return_value=bundled), patch.dict(sys.modules, {'control_processes': SimpleNamespace(processes=lambda: {'ui': []})}), patch('receiver_package_attestation.package_matches', return_value=True), patch('prelaunch_handoff_runtime.lookup_before_input', return_value=(reply, 9)) as lookup, patch('prelaunch_handoff_runtime.write_json_once'), patch('prelaunch_handoff_runtime.PrelaunchOwner') as owner:
                    self.assertEqual(cycle.begin()['status'], 'accepted')
                    self.assertIs(lookup.call_args.kwargs['verify_ready'], revalidate_client if bundled else None)
                    self.assertEqual(owner.call_args.args[2], 9)
                    self.assertEqual(owner.call_args.kwargs['lookup_reply'], reply)
                    owner.return_value.begin.assert_called_once()

    def test_unconfirmed_read_process_stop_cannot_launch_receiver(self):
        cycle = self.cycle()
        with patch('runtime_bundle.active', return_value=True), patch.dict(sys.modules, {'control_processes': SimpleNamespace(processes=lambda: {'ui': []})}), patch('receiver_package_attestation.package_matches', return_value=True), patch('prelaunch_handoff_runtime.lookup_before_input', side_effect=LunaChildStopError('stop unknown')), patch('prelaunch_handoff_runtime.PrelaunchOwner') as owner:
            self.assertEqual(cycle.begin()['status'], 'attention')
            owner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
