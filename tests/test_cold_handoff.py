import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/runtime'))
import input_start_handoff as handoff
import orphan_reconcile as recovery

class ColdHandoffTests(unittest.TestCase):
    def test_slow_initial_authorization_does_not_relax_later_checks(self):
        client = handoff.HandoffClient(path='/unused', run='a' * 32, token='b' * 32,
                                       controller={'pid': 12, 'startTicks': 34}, controller_uid=56)
        sock = Mock(); sock.__enter__ = Mock(return_value=sock); sock.__exit__ = Mock(return_value=False)
        sock.getsockopt.return_value = handoff.struct.pack('3i', 12, 56, 5000)
        timeout = [None]; sock.settimeout.side_effect = lambda value: timeout.__setitem__(0, value)
        reply = {'run': 'a' * 32, 'challenge': 'c' * 32, 'controller': client.controller, 'inputStarted': True}
        def receive(_):
            if not client.authenticated and timeout[0] < 1: raise TimeoutError('cold authorization')
            return reply
        with patch.object(handoff.socket, 'SO_PEERCRED', 17, create=True), patch.object(handoff.socket, 'socket', return_value=sock), patch.object(handoff, '_send'), patch.object(handoff, '_receive', side_effect=receive), patch.object(handoff.secrets, 'token_hex', return_value='c' * 32):
            self.assertTrue(client.check()); self.assertEqual(timeout[0], 3)
            self.assertTrue(client.check()); self.assertEqual(timeout[0], .5)
            sock.getsockopt.return_value = handoff.struct.pack('3i', 99, 56, 5000)
            self.assertFalse(client.check())

    def test_not_ready_archive_requires_exit_and_no_sensor_evidence(self):
        for mode in ('clean', 'journal', 'ready', 'live', 'different-process'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                cpath = Path(d) / 'controller'; bpath = Path(d) / 'receiver'
                cpath.mkdir(); bpath.mkdir()
                run = 'a' * 32; owner = os.getuid(); group = os.getgid()
                intent = {'stage': 'receiver-launch-intent', 'run': run, 'generation': 1}
                proc = {'pid': 100, 'startTicks': 200, 'status': {'Uid': ' '.join([str(owner)] * 4)}}
                receiver = {'pid': 101, 'startTicks': 201}
                receipt = {'status': 'not-ready', 'process': receiver}
                start = {'process': receiver if mode != 'different-process' else proc}
                def write(path, value, permissions):
                    path.write_text(json.dumps(value)); path.chmod(permissions)
                write(cpath / 'receiver-launch-intent.json', intent, 0o640)
                write(bpath / 'request.json', {'schema': 1, 'appId': 'org.magicsirimote.app', 'run': run}, 0o660)
                write(bpath / 'controller-start.json', {'schema': 1, 'appId': 'org.magicsirimote.app', 'run': run, 'process': proc}, 0o660)
                if mode == 'journal': (bpath / 'borrowed-active').mkdir()
                if mode == 'ready': (bpath / ('receiver-ready-' + run + '.json')).write_text('{}')
                c = os.open(cpath, os.O_RDONLY); b = os.open(bpath, os.O_RDONLY)
                lease = Mock(); lease.dirfd = c; lease.held.return_value = True
                try:
                    with patch.object(recovery.bundle, 'active', return_value=True), patch.object(recovery, '_ended', return_value=mode != 'live'), patch.object(recovery.package, 'package_matches', return_value=True), patch.object(recovery, 'read_start', return_value=start), patch.object(recovery, 'read_receipt', return_value=receipt):
                        def archive():
                            return recovery.archive_not_ready(c=c, b=b, intent=intent, intent_stat=(cpath / 'receiver-launch-intent.json').stat(), receipt=receipt,
                                receiver_state=bpath, controller_app='controller', receiver_app='receiver', receiver_package='package', pin={}, lease=lease, owner=owner, group=group, state_uid=owner)
                        if mode in ('live', 'different-process'):
                            with self.assertRaises(RuntimeError): archive()
                        else:
                            result = archive()
                            if mode == 'clean':
                                self.assertEqual(result['priorOutcome'], 'receiver-not-ready-before-sensors')
                                self.assertNotIn('sensorStopVerified', result)
                                self.assertTrue((bpath / ('request-not-ready-' + run + '.json')).exists())
                            else: self.assertIsNone(result)
                    self.assertEqual((cpath / 'receiver-launch-intent.json').exists(), mode != 'clean')
                finally: os.close(c); os.close(b)

if __name__ == '__main__': unittest.main()
