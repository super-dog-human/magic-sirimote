import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('pairing_flow', Path(__file__).resolve().parents[1] / 'src/pairing/flow.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
REMOTE = 'aa:bb:cc:dd:ee:ff'
TV = '11:22:33:44:55:66'


class Bus:
    def __init__(self): self.jobs = {}; self.sent = []; self.incoming = []
    def request(self, tag, method, params, **kw):
        self.jobs[tag] = True; self.sent.append((tag, method, params))
    def cancel(self, tag, completed=False): self.jobs.pop(tag, None)
    def events(self):
        while self.incoming:
            tag, value = self.incoming.pop(0); self.jobs.pop(tag, None)
            yield tag, value


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.flow = m.PairingFlow(self.bus, lambda value: None)
        self.flow.target = REMOTE; self.flow.adapter = TV
    def reply(self, tag, **kw): self.flow.on_reply(tag, {'returnValue': True, **kw})
    def test_refuse_active_main(self):
        self.flow.phase = 'scanned'; self.flow.candidates = {REMOTE: {'address':REMOTE,'paired':False}}; self.flow.pair()
        with self.assertRaisesRegex(RuntimeError, 'Stop the main'):
            self.reply('pair-idle', cleanStop=False, startup={'enabled': False})
        self.assertFalse(any(x[1] == 'adapter/pair' for x in self.bus.sent))
    def test_cached_scan_is_not_proof(self):
        self.flow.phase = 'ready'; self.flow.scan()
        self.reply('scan', devices=[{'address': REMOTE, 'name': 'Siri Remote'}])
        self.assertEqual(self.flow.candidates[REMOTE]['source'], 'scan-list')
        self.reply('scan', device={'address': REMOTE, 'name': 'Siri Remote'})
        self.flow.stop_scan(); self.flow.pair()
        self.assertEqual(self.bus.sent[-1][1], 'main/status')
    def test_pair_already_paired_is_rejected(self):
        self.flow.phase = 'scanned'; self.flow.candidates = {REMOTE: {'address': REMOTE, 'paired': True}}
        with self.assertRaisesRegex(ValueError, 'already paired'): self.flow.pair()
    def test_success_immediately_after_verified_identity(self):
        self.reply('pair', address=REMOTE, request='endPairing')
        self.reply('paired-check', devices=[{'address': REMOTE, 'paired': True}])
        self.reply('hid-check', address=REMOTE, adapterAddress=TV, connected=True, connecting=False)
        self.assertEqual(self.bus.sent[-1][2]['reportData'], [240, 175])
        self.reply('initialize')
        self.reply('identity-client', address=REMOTE, adapterAddress=TV, clientId='005')
        self.reply('identity-services')
        self.reply('identity-inventory', address=REMOTE, adapterAddress=TV, services=[
            {'service':'0000180a-0000-1000-8000-00805f9b34fb','characteristics':[
                {'characteristic':'00002a25-0000-1000-8000-00805f9b34fb'},
                {'characteristic':'00002a26-0000-1000-8000-00805f9b34fb'}]}])
        self.reply('identity-serial', address=REMOTE, adapterAddress=TV,
            service='0000180a-0000-1000-8000-00805f9b34fb', values=[
                {'characteristic':'00002a25-0000-1000-8000-00805f9b34fb','value':{'bytes':list(b'DL0000000000')}}])
        self.assertTrue(all(len(params.get('characteristics',[])) <= 1 for _,_,params in self.bus.sent))
        self.reply('identity-firmware', address=REMOTE, adapterAddress=TV,
            service='0000180a-0000-1000-8000-00805f9b34fb', values=[
                {'characteristic':'00002a25-0000-1000-8000-00805f9b34fb', 'value':{'bytes':list(b'DL0000000000')}},
                {'characteristic':'00002a26-0000-1000-8000-00805f9b34fb', 'value':{'bytes':list(b'01004102200070033000070131001800B000410240001508')}}])
        self.assertEqual(self.flow.phase, 'success')
        sent = list(self.bus.sent)
        self.flow.tick()
        self.assertEqual(self.bus.sent, sent)  # No delayed retention polling.
    def test_unknown_delivery_fails_without_retry(self):
        self.flow.initialize(); before = len(self.bus.sent)
        self.bus.incoming = [('initialize', {'returnValue': False, 'errorText': 'Request timed out'})]
        self.flow.tick()
        self.assertEqual(self.flow.phase, 'failed'); self.assertEqual(len(self.bus.sent), before)
    def test_other_peer_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Wrong pairing peer'):
            self.reply('pair', address=TV, request='confirmPasskey')
        self.assertFalse(self.bus.sent)
    def test_pin_not_guessed(self):
        with self.assertRaisesRegex(RuntimeError, 'no code was guessed'):
            self.reply('pair', address=REMOTE, request='enterPasskey')
        self.assertFalse(self.bus.sent)
    def test_paired_flag_loss_fails(self):
        with self.assertRaisesRegex(ValueError, 'not confirmed'):
            self.reply('paired-check', devices=[{'address': REMOTE, 'paired': False}])
    def test_advertised_name_and_service_without_top_level_name(self):
        raw = [2,1,6,3,2,18,24,3,255,76,0,13,8] + list(b'DL0000000000')
        ad = m.advertising({'scanRecord': raw})
        self.assertTrue(ad['apple']); self.assertTrue(ad['hid'])
        self.assertEqual(ad['name'], 'DL0000000000')
        self.assertTrue(m.plausible({'scanRecord': raw}))
        self.assertFalse(m.plausible({'name': 'Bluetooth keyboard'}))
    def test_truncated_advertising_is_not_a_candidate(self):
        self.assertEqual(m.advertising({'scanRecord': [12, 8, 65]}), {})
    def test_routing_requires_pairing_and_does_not_switch_saved_remote(self):
        remote = {'address': REMOTE, 'name': 'DL0000000000', 'paired': True}
        self.assertEqual(m.paired_route([remote], REMOTE), remote)
        self.assertEqual(m.paired_route([remote], ''), remote)
        self.assertIsNone(m.paired_route([remote], TV))
        self.assertIsNone(m.paired_route([{**remote, 'paired': False}], REMOTE))
        self.assertIsNone(m.paired_route([remote, {**remote, 'address': TV}], ''))
    def test_exact_target_automatic_attempt_is_once(self):
        self.flow.phase = 'ready'; self.flow.was_paired = False
        self.flow.scan_and_pair()
        self.reply('scan', devices=[{'address': REMOTE, 'paired': False}])
        self.assertFalse(self.flow.auto_pair)
        self.assertEqual(self.flow.phase, 'pair-preflight')
        self.assertEqual(sum(x[1] == 'main/status' for x in self.bus.sent), 1)

    def test_blank_name_still_routes_saved_paired_address(self):
        self.assertIsNotNone(m.paired_route([{'address':REMOTE,'name':'','paired':True}], REMOTE))
        self.assertIsNone(m.paired_route([{'address':TV,'name':'','paired':True}], REMOTE))
    def test_wrong_serial_response_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Wrong identity response'):
            self.reply('identity-firmware',address=TV,adapterAddress=TV)


if __name__ == '__main__': unittest.main()
