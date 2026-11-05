import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/runtime'))
from takeover_recovery import execute


class Prepared(Exception):
    pass


class ReadinessTests(unittest.TestCase):
    def fixture(self):
        now = [0.0]
        stop = Mock(); stop.is_set.return_value = False
        stop.wait.side_effect = lambda seconds: now.__setitem__(0, now[0] + seconds)
        watch = Mock(); watch.is_open.return_value = True
        watch.snapshot.side_effect = lambda: {'generation': 2} if now[0] >= .3 else None
        lease = Mock(); lease.held.return_value = True
        prepare = Mock(side_effect=Prepared)
        args = dict(run='a'*32, watch=watch, lease=lease, stop=stop,
                    controller_state='/c', receiver_state='/r', controller_app='/ca',
                    receiver_app='/ra', receiver_package='/pkg', pin={},
                    prepare_fn=prepare, write_request=Mock(), launcher_factory=Mock(),
                    clock=lambda: now[0], timeout=1)
        return args, now

    def run_until_preparation(self, args):
        with patch('runtime_bundle.active', return_value=False), patch('receiver_package_attestation.package_matches', return_value=True):
            with self.assertRaises(Prepared): execute(**args)
        args['prepare_fn'].assert_called_once()
        args['write_request'].assert_not_called()
        args['launcher_factory'].assert_not_called()

    def test_connection_loss_before_entry_waits_without_creating_records(self):
        args, now = self.fixture()
        self.run_until_preparation(args)
        self.assertGreaterEqual(now[0], .3)

    def test_generation_change_during_package_check_needs_new_observation(self):
        args, now = self.fixture()
        args['watch'].snapshot.side_effect = [{'generation': 1}, {'generation': 2}, {'generation': 2}, {'generation': 2}]
        self.run_until_preparation(args)
        self.assertEqual(now[0], .1)

    def test_stop_owner_loss_closed_watch_and_timeout_never_prepare(self):
        for kind in ('stop', 'lease', 'watch', 'timeout'):
            args, now = self.fixture()
            args['watch'].snapshot.return_value = None
            args['watch'].snapshot.side_effect = None
            if kind == 'stop': args['stop'].is_set.side_effect = lambda: now[0] >= .2
            if kind == 'lease': args['lease'].held.side_effect = lambda: now[0] < .2
            if kind == 'watch': args['watch'].is_open.side_effect = lambda: now[0] < .2
            with patch('runtime_bundle.active', return_value=False):
                with self.assertRaises(RuntimeError): execute(**args)
            args['prepare_fn'].assert_not_called()
            args['write_request'].assert_not_called()
            args['launcher_factory'].assert_not_called()

    def test_package_mismatch_is_not_retried(self):
        args, now = self.fixture()
        args['watch'].snapshot.side_effect = lambda: {'generation': 2}
        with patch('runtime_bundle.active', return_value=False), patch('receiver_package_attestation.package_matches', return_value=False) as verify:
            with self.assertRaisesRegex(RuntimeError, 'package mismatch'): execute(**args)
        verify.assert_called_once(); args['prepare_fn'].assert_not_called()

    def test_failure_after_preparation_is_never_replayed(self):
        args, now = self.fixture()
        args['prepare_fn'].side_effect = RuntimeError('published takeover unconfirmed')
        with patch('runtime_bundle.active', return_value=False), patch('receiver_package_attestation.package_matches', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'published takeover'): execute(**args)
        args['prepare_fn'].assert_called_once()
        args['write_request'].assert_not_called()
        args['launcher_factory'].assert_not_called()


if __name__ == '__main__': unittest.main()
