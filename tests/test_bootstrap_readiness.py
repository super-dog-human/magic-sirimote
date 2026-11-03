"""Late Bluetooth startup with no device access or real waiting."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/runtime'))
import bootstrap_connect as boot
from borrowed_gatt_view import ADAPTER
from pumping_luna_client import LunaCallError


class Scenario:
    def __init__(self, delay=0, failure='inventory'):
        self.now = 0
        self.delay, self.failure = delay, failure
        self.stop_at = self.lose_lease_at = float('inf')
        self.calls, self.events, self.waits = [], [], []
        self.reservations = self.retirements = self.recoveries = 0
        self.connected = self.auto_connected = self.prior_intent = False
        self.write_outcome = 'success'
        self.pre_dispatch = lambda: True

    def held(self): return self.now < self.lose_lease_at
    def is_set(self): return self.now >= self.stop_at
    def wait(self, seconds): self.waits.append(seconds); self.now += seconds
    def reserve(self, _):
        self.reservations += 1
        if self.prior_intent: raise FileExistsError()
    def retire(self, _): self.retirements += 1
    def recover(self, **_): self.recoveries += 1; return False
    def factory(self, **kwargs):
        if 'pre_dispatch' in kwargs: self.pre_dispatch = kwargs['pre_dispatch']
        return self.client

    def client(self, method, params, **kwargs):
        self.calls.append((self.now, method))
        late = self.now < self.delay
        if method == 'device/getStatus':
            if late and self.failure == 'timeout': raise LunaCallError('read timeout')
            if late and self.failure == 'inventory': return {'returnValue': False}
            target = {'address': boot.TARGET, 'name': boot.NAME, 'paired': True, 'blocked': False, 'pairing': False}
            if late and self.failure == 'unpaired': target['paired'] = False
            if late and self.failure == 'blocked': target['blocked'] = True
            if late and self.failure == 'wrong-name': target['name'] = 'Wrong_remote'
            return {'returnValue': True, 'devices': [] if late and self.failure == 'missing' else [target]}
        if method in ('hid/getStatus', 'gatt/getStatus'):
            if late and self.failure == method.split('/')[0]: return {'returnValue': False, 'errorCode': 1}
            if self.write_outcome == 'uncertain' and any(m == 'hid/connect' for _, m in self.calls):
                return {'returnValue': False, 'errorCode': 1}
            return {'returnValue': True, 'address': boot.TARGET,
                    'adapterAddress': '02:00:00:00:00:fe' if late and self.failure == 'wrong-adapter' else ADAPTER,
                    'connected': self.connected or self.auto_connected and not late,
                    'connecting': False, 'connectRequest': False}
        if method == 'hid/connect':
            assert self.reservations == 1 and self.pre_dispatch()
            if self.write_outcome == 'rejected': return {'returnValue': False}
            if self.write_outcome == 'uncertain': raise LunaCallError('write outcome unknown')
            self.connected = True
            if self.write_outcome == 'lost-ack': raise LunaCallError('lost acknowledgement')
            return {'returnValue': True}
        raise AssertionError(method)

    def run(self, **kwargs):
        return boot.bootstrap(lease=self, stop=self, deadline=self.now + 10,
                              clock=lambda: self.now, client_factory=self.factory,
                              reserve=self.reserve, retire=self.retire, recover=self.recover,
                              trace=self.events.append, wait_for_ready=kwargs.get('wait_for_ready', True))

    def connects(self): return [t for t, method in self.calls if method == 'hid/connect']


class BootstrapReadinessTests(unittest.TestCase):
    def test_service_may_be_late_beyond_old_120_second_budget(self):
        s = Scenario(delay=135)
        self.assertTrue(s.run())
        self.assertEqual(s.connects(), [135])
        self.assertEqual(s.reservations, 1)
        self.assertEqual(s.retirements, 1)
        self.assertEqual(s.waits, [5] * 27)
        self.assertEqual(s.events.count('bootstrap-inventory-service-error'), 1)

    def test_every_retry_revalidates_peer_and_both_profiles(self):
        for reason in ('timeout', 'missing', 'unpaired', 'blocked', 'wrong-name', 'hid', 'gatt', 'wrong-adapter'):
            with self.subTest(reason=reason):
                s = Scenario(delay=15, failure=reason)
                self.assertTrue(s.run())
                self.assertEqual(s.connects(), [15])
                self.assertEqual(s.reservations, 1)

    def test_auto_reconnect_during_readiness_wait_needs_no_connect_request(self):
        s = Scenario(delay=15); s.auto_connected = True
        self.assertTrue(s.run())
        self.assertEqual(s.connects(), [])
        self.assertEqual(s.reservations, 0)
        self.assertEqual(s.retirements, 1)

    def test_standby_stop_or_lease_loss_interrupts_readiness_wait(self):
        for field in ('stop_at', 'lose_lease_at'):
            with self.subTest(field=field):
                s = Scenario(delay=1000); setattr(s, field, 15)
                self.assertFalse(s.run())
                self.assertEqual(s.now, 15)
                self.assertEqual(s.reservations, 0)
                self.assertEqual(s.connects(), [])

    def test_preexisting_uncertain_intent_is_not_repeated(self):
        s = Scenario(delay=15); s.prior_intent = True
        self.assertFalse(s.run())
        self.assertEqual(s.recoveries, 1)
        self.assertEqual(s.reservations, 1)
        self.assertEqual(s.connects(), [])

    def test_write_failure_never_returns_to_readiness_retries(self):
        for outcome in ('uncertain', 'rejected', 'lost-ack'):
            with self.subTest(outcome=outcome):
                s = Scenario(delay=15); s.write_outcome = outcome
                self.assertEqual(s.run(), outcome == 'lost-ack')
                self.assertEqual(s.connects(), [15])
                self.assertEqual(s.reservations, 1)
                self.assertLessEqual(s.now, 25)
                self.assertEqual(s.retirements, int(outcome == 'lost-ack'))

    def test_bounded_callers_keep_the_existing_preflight_failure_behavior(self):
        s = Scenario(delay=15)
        self.assertFalse(s.run(wait_for_ready=False))
        self.assertEqual(s.now, 0)
        self.assertEqual(s.reservations, 0)
        self.assertEqual(s.connects(), [])


if __name__ == '__main__':
    unittest.main()
