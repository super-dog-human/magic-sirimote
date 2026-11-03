"""Lifecycle commands refuse conflicts and publish cooperative stop requests."""
import importlib.util
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/integrated'), str(ROOT / 'src/native')]
import control
from native_manager import RuntimeSetup, consume_installer


def found(**changes):
    return dict({'controller': [], 'receiver': [], 'legacy': [], 'ui': []}, **changes)


class ControlTests(unittest.TestCase):
    def test_old_native_window_blocks_input_before_launch_intent(self):
        import postconnect_supervisor_cycle as cycle
        from unittest.mock import Mock
        owner = cycle.SupervisorCycle.__new__(cycle.SupervisorCycle)
        owner.lease = Mock(); owner.lease.held.return_value = True
        with patch.object(cycle.bundle, 'active', return_value=True), patch('control_processes.processes', return_value=found(ui=[{'pid': 8}])):
            self.assertEqual(owner.begin(), {'status': 'not-ready'})

    def test_launcher_cannot_reuse_an_existing_native_window(self):
        import tv_launch
        from unittest.mock import Mock
        invoke = Mock()
        launcher = tv_launch.Launcher('a' * 32, invoke=invoke)
        with patch.object(tv_launch.bundle, 'active', return_value=True), patch('control_processes.processes', return_value=found(ui=[{'pid': 8}])):
            self.assertEqual(launcher.launch('B', 'a' * 32), 'rejected')
        invoke.assert_not_called()

    def test_start_refuses_previous_runtime_before_loading_device_settings(self):
        with patch.object(control, 'processes', return_value=found(legacy=[{'pid': 5}])), patch.object(control, 'load') as load:
            with self.assertRaisesRegex(RuntimeError, 'previous input'):
                control.prepare_start()
            load.assert_not_called()

    def test_configuration_refuses_live_worker_or_unfinished_journal(self):
        for processes, clean in ((found(receiver=[{'pid': 5}]), True), (found(), False)):
            with patch.object(control, 'processes', return_value=processes), patch.object(control, 'clean_state', return_value=clean), patch.object(control, 'save') as save:
                with self.assertRaises(RuntimeError): control.configure({})
                save.assert_not_called()

    def test_missing_controller_is_not_reported_as_clean_stop_with_worker_or_journal(self):
        for processes, clean in ((found(receiver=[{'pid': 9}]), True), (found(), False)):
            with patch.object(control, 'processes', return_value=processes), patch.object(control, 'clean_state', return_value=clean):
                self.assertEqual(control.stop()['status'], 'needs-recovery')

    def test_gui_start_closes_only_after_service_accepts_configuration_and_start(self):
        class Bus:
            def __init__(self): self.calls = []
            def request(self, method, params): self.calls.append(method); return {'returnValue': True}
        with tempfile.TemporaryDirectory() as d:
            bus = Bus(); app = RuntimeSetup(Path(d), bus)
            values = {'schema': 1, 'remoteAddress': 'aa:bb:cc:dd:ee:10', 'adapterAddress': 'aa:bb:cc:dd:ee:20', 'remoteName': 'Remote', 'gyroEnabled': True}
            with patch('native_manager.settings.save'):
                app.apply(values, True)
            self.assertTrue(app.done)
            self.assertEqual(bus.calls, ['configure', 'start'])

    def test_installer_unknown_result_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            nonce = 'a' * 32
            (Path(d) / ('install-result-' + nonce + '.json')).write_text('{"status":"pending"}')
            with patch('native_manager.STATE', Path(d)):
                self.assertFalse(consume_installer({'installerRequest': nonce}, lambda *_: self.fail('replayed')))


if __name__ == '__main__': unittest.main()
