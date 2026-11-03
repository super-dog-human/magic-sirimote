"""Routing and setup UI checks without native libraries or Bluetooth hardware."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for name, relative in [('pairing_flow', 'pairing/flow.py'), ('pairing_transport', 'pairing/transport.py')]:
    sys.path.insert(0, str(ROOT / 'src/native'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'src' / relative)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module)
spec = importlib.util.spec_from_file_location('pairing_screen', ROOT / 'src/integrated/pairing_screen.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
REMOTE = 'aa:bb:cc:dd:ee:10'; TV = 'aa:bb:cc:dd:ee:20'


class Bus:
    def __init__(self): self.jobs = {}; self.sent = []
    def __enter__(self): return self
    def __exit__(self, *_): self.jobs.clear()
    def request(self, tag, method, params, **kw): self.jobs[tag] = True; self.sent.append((tag, method, params))
    def events(self): return iter(())
    def cancel(self, tag, **kw): self.jobs.pop(tag, None)


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.bus = Bus(); self.app = types.SimpleNamespace(state=Path(self.folder.name),
            values={'remoteAddress': REMOTE, 'adapterAddress': TV, 'remoteName': 'DL0000000000',
                    'gyroEnabled': True, 'gyroSensitivity': 3}, bus=Mock(), stop_runtime=Mock(), apply=Mock(), done=False)
        with patch.object(m, 'BluetoothBus', return_value=self.bus): self.screen = m.PairingScreen(self.app)
        self.addCleanup(self.screen.close)
    def test_paired_remote_routes_to_settings_without_writes(self):
        self.screen.flow.adapter = TV
        self.screen.flow.on_reply('devices', {'returnValue': True, 'devices': [
            {'address': REMOTE, 'name': 'DL0000000000', 'paired': True}]})
        self.screen.tick()
        self.assertFalse(self.screen.visible); self.app.stop_runtime.assert_not_called(); self.app.apply.assert_not_called()
    def test_unpaired_remote_shows_start_without_automatic_pair(self):
        self.screen.flow.on_reply('devices', {'returnValue': True, 'devices': []})
        self.screen.tick()
        self.assertTrue(self.screen.visible); self.assertEqual(self.screen.labels()[0], 'Start pairing')
        self.assertFalse(any(method=='adapter/pair' for _,method,_ in self.bus.sent))
    def test_start_waits_for_cleanup(self):
        self.screen.flow.phase = 'ready'; self.screen.route = 'start'
        self.screen.start(); self.app.stop_runtime.assert_called_once()
        self.app.bus.request.return_value = {'returnValue':True,'cleanStop':False,'startup':{'enabled':False}}
        self.screen.tick()
        self.assertEqual(self.screen.route,'stopping')
        self.assertFalse(any(method=='le/startScan' for _,method,_ in self.bus.sent))
    def test_success_configures_once_without_assignments(self):
        self.screen.flow.phase = 'success'; self.screen.route = 'pairing'; self.screen.flow.adapter = TV
        self.screen.tick(); self.screen.tick()
        self.app.apply.assert_called_once()
        self.assertEqual(self.app.apply.call_args.args[0]['remoteAddress'],REMOTE)
        self.assertFalse(self.screen.visible)


if __name__ == '__main__': unittest.main()
