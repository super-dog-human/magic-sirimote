import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('pairing_flow', Path(__file__).resolve().parents[1] / 'src/pairing/flow.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
REMOTE = 'aa:bb:cc:dd:ee:ff'
TV = '11:22:33:44:55:66'
AD = [2,1,6,3,2,18,24,15,255,76,0,138,7,102,2,2,170,187,204,221,238,255,8]
DIS = '0000180a-0000-1000-8000-00805f9b34fb'
def uuid(short): return '0000' + short + '-0000-1000-8000-00805f9b34fb'



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
    def test_transient_firmware_read_is_retried_without_writes(self):
        now=[0.0]; self.flow.clock=lambda:now[0]
        self.flow.phase='identity';self.flow.product=0x026d
        self.flow.pending_serial='SERIAL';self.flow.identity_client='1'
        self.bus.incoming.append(('identity-firmware',{'returnValue':False,'errorCode':174}))
        self.flow.tick();self.assertFalse(self.bus.sent)
        now[0]=.25;self.flow.tick()
        self.assertEqual(self.bus.sent[-1][1],'gatt/readCharacteristicValues')
        self.assertEqual(self.bus.sent[-1][2]['characteristics'],[uuid('2a26')])
        self.reply('identity-firmware',address=REMOTE,adapterAddress=TV,service=DIS,
                   values=[{'characteristic':uuid('2a26'),'value':{'bytes':list(b'0116')}}])
        self.assertEqual(self.flow.serial,'SERIAL')
        self.assertEqual(self.flow.firmware,'0116')
        self.assertEqual(self.flow.phase,'connecting')
        self.assertFalse(any(method in ('adapter/unpair','hid/internal/setReport') for _,method,_ in self.bus.sent))

    def test_firmware_retry_is_bounded_and_does_not_accept_missing_identity(self):
        now=[0.0];self.flow.clock=lambda:now[0]
        self.flow.phase='identity';self.flow.product=0x026d
        self.flow.pending_serial='SERIAL';self.flow.identity_client='1'
        for i in range(3):
            self.bus.incoming.append(('identity-firmware',{'returnValue':False,'errorCode':174,'errorText':'read failed'}))
            self.flow.tick();now[0]+=1;self.flow.tick()
        self.assertEqual(self.flow.phase,'failed')
        self.assertIsNone(self.flow.serial)
        self.assertEqual(sum(method=='gatt/readCharacteristicValues' for _,method,_ in self.bus.sent),2)
        self.flow.tick();self.assertEqual(len(self.bus.sent),2)

    def test_other_read_errors_are_not_retried(self):
        self.flow.phase='identity';self.flow.product=0x026d;self.flow.pending_serial='SERIAL'
        self.bus.incoming.append(('identity-firmware',{'returnValue':False,'errorCode':1,'errorText':'Denied'}))
        self.flow.tick();self.assertEqual(self.flow.phase,'failed');self.assertFalse(self.bus.sent)

    def test_refuse_active_main(self):
        self.flow.phase = 'scanned'; self.flow.candidates = {REMOTE: {'address':REMOTE,'paired':False}}; self.flow.pair()
        with self.assertRaisesRegex(RuntimeError, 'Stop the main'):
            self.reply('pair-idle', cleanStop=False, startup={'enabled': False})
        self.assertFalse(any(x[1] == 'adapter/pair' for x in self.bus.sent))
    def test_cached_scan_is_not_proof(self):
        self.flow.phase = 'ready'; self.flow.scan()
        self.reply('scan', devices=[{'address': REMOTE, 'name': 'Siri Remote', 'scanRecord': AD}])
        self.assertEqual(self.flow.candidates[REMOTE]['source'], 'scan-list')
        self.reply('scan', device={'address': REMOTE, 'name': 'Siri Remote', 'scanRecord': AD})
        self.assertEqual(self.flow.phase, 'pair-preflight')
        self.assertEqual(self.bus.sent[-1][1], 'main/status')
    def test_pair_already_paired_is_rejected(self):
        self.flow.phase = 'scanned'; self.flow.candidates = {REMOTE: {'address': REMOTE, 'paired': True}}
        with self.assertRaisesRegex(ValueError, 'already paired'): self.flow.pair()
    def test_success_immediately_after_verified_identity(self):
        self.flow.pair_requested = True
        self.reply('pair', address=REMOTE, request='endPairing')
        self.reply('paired-check', devices=[{'address': REMOTE, 'paired': True}])
        self.assertFalse(any(x[1] == 'hid/internal/setReport' for x in self.bus.sent))
        self.reply('identity-client', address=REMOTE, adapterAddress=TV, clientId='005')
        self.reply('identity-services')
        self.reply('identity-inventory', address=REMOTE, adapterAddress=TV, services=[
            {'service':'0000180a-0000-1000-8000-00805f9b34fb','characteristics':[
                {'characteristic':'00002a50-0000-1000-8000-00805f9b34fb'},
                {'characteristic':'00002a25-0000-1000-8000-00805f9b34fb'},
                {'characteristic':'00002a26-0000-1000-8000-00805f9b34fb'}]}])
        self.reply('identity-product', address=REMOTE, adapterAddress=TV, service=DIS,
            values=[{'characteristic':uuid('2a50'),'value':{'bytes':[1,76,0,102,2,0,0]}}])
        self.reply('identity-serial', address=REMOTE, adapterAddress=TV,
            service='0000180a-0000-1000-8000-00805f9b34fb', values=[
                {'characteristic':'00002a25-0000-1000-8000-00805f9b34fb','value':{'bytes':list(b'DL0000000000')}}])
        self.assertTrue(all(len(params.get('characteristics',[])) <= 1 for _,_,params in self.bus.sent))
        self.reply('identity-firmware', address=REMOTE, adapterAddress=TV,
            service='0000180a-0000-1000-8000-00805f9b34fb', values=[
                {'characteristic':'00002a25-0000-1000-8000-00805f9b34fb', 'value':{'bytes':list(b'DL0000000000')}},
                {'characteristic':'00002a26-0000-1000-8000-00805f9b34fb', 'value':{'bytes':list(b'01004102200070033000070131001800B000410240001508')}}])
        self.assertFalse(any(x[1] == 'hid/internal/setReport' for x in self.bus.sent))
        self.reply('hid-check', address=REMOTE, adapterAddress=TV, connected=True, connecting=False)
        self.assertEqual(self.bus.sent[-1][2]['reportData'], [240, 175])
        self.reply('initialize')
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
        raw = AD + [13,8] + list(b'DL0000000000')
        ad = m.advertising({'scanRecord': raw})
        self.assertTrue(ad['apple']); self.assertTrue(ad['hid'])
        self.assertEqual(ad['name'], 'DL0000000000')
        self.assertTrue(m.plausible({'scanRecord': raw}))
        self.assertFalse(m.plausible({'name': 'Bluetooth keyboard'}))
    def test_truncated_advertising_is_not_a_candidate(self):
        self.assertEqual(m.advertising({'scanRecord': [12, 8, 65]}), {})
    def test_routing_requires_pairing_and_does_not_switch_saved_remote(self):
        remote = {'address': REMOTE, 'name': 'DL0000000000', 'paired': True, 'scanRecord': AD}
        self.assertEqual(m.paired_route([remote], REMOTE), remote)
        self.assertEqual(m.paired_route([remote], ''), remote)
        self.assertIsNone(m.paired_route([remote], TV))
        self.assertIsNone(m.paired_route([{**remote, 'paired': False}], REMOTE))
        self.assertIsNone(m.paired_route([remote, {**remote, 'address': TV}], ''))
    def test_cached_pair_hint_is_not_a_new_pairing_candidate(self):
        remote = {'address': REMOTE, 'name': 'DL0000000000', 'paired': True,
                  'classOfDevice': 0x1F00, 'scanRecord': []}
        self.assertEqual(m.paired_route([remote], ''), remote)
        self.assertFalse(m.plausible(remote))
        for change in ({'paired': False}, {'blocked': True}, {'pairing': True},
                       {'classOfDevice': 0}, {'name': 'Keyboard'}, {'scanRecord': [1]}):
            self.assertIsNone(m.paired_route([{**remote, **change}], ''))
        self.assertIsNone(m.paired_route([remote], TV))
        self.assertIsNone(m.paired_route([remote, {**remote, 'address': TV}], ''))

    def test_exact_target_automatic_attempt_is_once(self):
        self.flow.phase = 'ready'; self.flow.was_paired = False
        self.flow.scan_and_pair()
        self.reply('scan', devices=[{'address': REMOTE, 'paired': False, 'scanRecord': AD}])
        self.assertFalse(self.flow.auto_pair)
        self.assertEqual(self.flow.phase, 'pair-preflight')
        self.assertEqual(sum(x[1] == 'main/status' for x in self.bus.sent), 1)

    def test_first_available_supported_remote_is_automatically_paired_once(self):
        self.flow.target = None; self.flow.phase = 'ready'; self.flow.scan()
        self.reply('scan', devices=[
            {'address': TV, 'name': 'Siri Remote'},
            {'address': TV, 'paired': True, 'scanRecord': AD},
            {'address': TV, 'blocked': True, 'scanRecord': AD},
            {'address': TV, 'pairing': True, 'scanRecord': AD},
            {'address': REMOTE, 'paired': False, 'scanRecord': AD},
            {'address': TV, 'paired': False, 'scanRecord': AD}])
        self.assertEqual(self.flow.target, REMOTE)
        self.assertEqual(self.flow.phase, 'pair-preflight')
        self.assertNotIn('scan', self.bus.jobs)
        # Queued events, including a late timeout, must not start another pair.
        self.reply('scan', device={'address': TV, 'scanRecord': AD})
        self.flow.on_reply('scan', {'returnValue':False,'errorText':'Request timed out'})
        self.assertEqual(self.flow.phase, 'pair-preflight')
        self.assertEqual(sum(method == 'main/status' for _,method,_ in self.bus.sent), 1)
        self.assertFalse(any(method == 'adapter/pair' for _,method,_ in self.bus.sent))
        self.reply('pair-idle', cleanStop=True, startup={'enabled':False})
        self.reply('pair-fresh', devices=[{'address':REMOTE,'paired':False}])
        self.assertEqual(self.bus.sent[-1], ('pair','adapter/pair',{'address':REMOTE,'subscribe':True}))

    def test_saved_target_is_not_replaced_by_other_advertisement(self):
        self.flow.phase = 'ready'; self.flow.scan_and_pair()
        self.reply('scan', device={'address':TV,'scanRecord':AD})
        self.assertEqual(self.flow.phase, 'scanning')
        self.assertFalse(self.flow.candidates)
        self.assertEqual(self.flow.target, REMOTE)

    def test_timeout_allows_a_new_automatic_search(self):
        self.flow.target = None; self.flow.phase = 'ready'; self.flow.scan()
        self.flow.on_reply('scan', {'returnValue':False,'errorText':'Request timed out'})
        self.assertEqual(self.flow.phase, 'scanned')
        self.flow.scan()
        self.reply('scan', device={'address':REMOTE,'scanRecord':AD})
        self.assertEqual(self.flow.phase, 'pair-preflight')

    def test_blank_name_still_routes_saved_paired_address(self):
        self.assertIsNotNone(m.paired_route([{'address':REMOTE,'name':'','paired':True}], REMOTE))
        self.assertIsNone(m.paired_route([{'address':TV,'name':'','paired':True}], REMOTE))
    def test_wrong_serial_response_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Wrong identity response'):
            self.reply('identity-firmware',address=TV,adapterAddress=TV)

    def test_names_and_apple_company_alone_are_rejected(self):
        for name in ('Siri Remote', 'Apple TV Remote', 'DL0000000000'):
            self.assertFalse(m.plausible({'name': name}))
        self.assertFalse(m.plausible({'scanRecord': [3,2,18,24,3,255,76,0]}))
        self.assertIsNone(m.paired_route([{'address': REMOTE, 'name': 'Siri Remote', 'paired': True}], ''))

    def test_other_products_vendors_and_ambiguous_advertisements_rejected(self):
        for index, byte in ((9, 77), (13, 110), (12, 8), (15, 3)):
            changed = list(AD); changed[index] = byte
            self.assertFalse(m.plausible({'scanRecord': changed}), (index, byte))
        self.assertFalse(m.plausible({'scanRecord': AD + [3,255,76,0]}))
        self.assertFalse(m.plausible({'scanRecord': AD[7:]}))  # no HID service
        self.assertFalse(m.plausible({'scanRecord': AD[:-1]}))

    def test_saved_address_does_not_bypass_new_pairing_filter(self):
        self.flow.phase = 'ready'; self.flow.scan_and_pair()
        self.reply('scan', devices=[{'address': REMOTE, 'name': 'Siri Remote'}])
        self.assertFalse(self.flow.candidates)
        self.assertFalse(any(x[1] == 'main/status' for x in self.bus.sent))

    def test_wrong_adapter_cannot_confirm_new_pair(self):
        with self.assertRaisesRegex(ValueError, 'Wrong TV adapter'):
            self.reply('pair', address=REMOTE, adapterAddress=REMOTE, request='endPairing')
        self.assertFalse(self.flow.pair_ended)

    def test_existing_bond_is_not_owned_by_unsolicited_completion(self):
        self.reply('pair', address=REMOTE, request='endPairing')
        self.reply('paired-check', devices=[{'address':REMOTE,'paired':True}])
        self.assertFalse(self.flow.owned_pair)

    def test_pair_preflight_refuses_existing_bond(self):
        self.reply('pair-idle', cleanStop=True, startup={'enabled': False})
        self.assertEqual(self.bus.sent[-1][0], 'pair-fresh')
        with self.assertRaisesRegex(ValueError, 'unpaired'):
            self.reply('pair-fresh', devices=[{'address': REMOTE, 'paired': True}])
        self.assertFalse(any(x[1] == 'adapter/pair' for x in self.bus.sent))

    def test_pair_preflight_accepts_only_selected_unpaired_target(self):
        self.reply('pair-fresh', devices=[{'address': REMOTE, 'paired': False}, {'address':TV,'paired':True}])
        self.assertEqual(self.bus.sent[-1][1], 'adapter/pair')
        self.assertEqual(self.bus.sent[-1][2]['address'], REMOTE)

    def test_pnp_namespace_vendor_product_and_length(self):
        for pnp in ([1,76,0,110,2,0,0], [2,76,0,102,2,0,0], [1,77,0,102,2,0,0], [1,76,0,102,2]):
            with self.assertRaisesRegex(ValueError, 'Only Siri Remote'):
                self.reply('identity-product', address=REMOTE,adapterAddress=TV,service=DIS,
                    values=[{'characteristic':uuid('2a50'),'value':{'bytes':pnp}}])
        self.assertFalse(any(x[1] == 'hid/internal/setReport' for x in self.bus.sent))

    def test_existing_identity_verification_does_not_write_or_unpair(self):
        self.flow.verify_identity(existing=True)
        self.flow.product = 0x0266
        self.flow.pending_serial = 'DL0000000000'
        self.reply('identity-firmware', address=REMOTE,adapterAddress=TV,service=DIS,
            values=[{'characteristic':uuid('2a26'),'value':{'bytes':list(b'01004102200070033000070131001800B000410240001508')}}])
        self.assertEqual(self.flow.phase, 'existing-verified')
        self.assertEqual([x[1] for x in self.bus.sent], ['gatt/connect'])
        self.flow.fail('unverified')
        self.assertFalse(any(x[1] == 'adapter/unpair' for x in self.bus.sent))

    def test_invalid_new_product_removes_only_owned_pairing(self):
        self.flow.owned_pair = True
        self.bus.incoming = [('identity-product', {'returnValue':True,'address':REMOTE,'adapterAddress':TV,
            'service':DIS,'values':[{'characteristic':uuid('2a50'),'value':{'bytes':[1,76,0,110,2,0,0]}}]})]
        self.flow.tick()
        self.assertEqual(self.flow.phase, 'rejecting')
        self.assertEqual(self.bus.sent[-1], ('reject-unpair','adapter/unpair',{'address':REMOTE}))
        self.reply('reject-unpair')
        self.reply('reject-check', devices=[{'address':REMOTE,'paired':False},{'address':TV,'paired':True}])
        self.assertEqual(self.flow.phase, 'failed')
        self.assertIn('new pairing removed', self.flow.message)

    def test_missing_removal_status_is_not_success(self):
        self.flow.owned_pair=True; self.flow.fail('unsupported')
        self.bus.incoming=[('reject-check',{'returnValue':True})]
        self.flow.tick()
        self.assertEqual(self.flow.phase,'failed')
        self.assertIn('removal could not be confirmed',self.flow.message)

    def test_failed_removal_is_not_repeated(self):
        self.flow.owned_pair = True; self.flow.fail('Unsupported product')
        self.bus.incoming = [('reject-unpair', {'returnValue':False,'errorText':'timed out'})]
        self.flow.tick()
        self.assertEqual(self.flow.phase,'failed')
        self.assertIn('removal could not be confirmed',self.flow.message)
        self.assertEqual(sum(x[1]=='adapter/unpair' for x in self.bus.sent),1)

    def test_unknown_input_start_delivery_does_not_remove_bond(self):
        self.flow.owned_pair=True; self.flow.initialize(); self.flow.fail('timed out')
        self.assertFalse(any(x[1]=='adapter/unpair' for x in self.bus.sent))

    def test_a1962_candidate_and_identity_allow_pairing_handoff(self):
        ad = list(AD); ad[13] = 109
        self.assertTrue(m.plausible({'scanRecord': ad}))
        self.flow.identity_client = '005'; self.flow.advertised_product = 0x026d
        self.reply('identity-product', address=REMOTE,adapterAddress=TV,service=DIS,
            values=[{'characteristic':uuid('2a50'),'value':{'bytes':[1,76,0,109,2,0,0]}}])
        self.assertEqual(self.flow.product, 0x026d)
        self.flow.pending_serial = 'DL0000000000'
        # Deliberately synthetic, not a claim about real A1962 firmware bytes.
        self.reply('identity-firmware', address=REMOTE,adapterAddress=TV,service=DIS,
            values=[{'characteristic':uuid('2a26'),'value':{'bytes':list(b'test-firmware')}}])
        self.assertEqual(self.bus.sent[-1][1], 'hid/getStatus')
        self.reply('hid-check', address=REMOTE,adapterAddress=TV,connected=True,connecting=False)
        self.reply('initialize')
        self.assertEqual(self.flow.phase, 'success')

    def test_advertisement_and_connected_product_must_agree(self):
        self.flow.advertised_product = 0x0266
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.reply('identity-product',address=REMOTE,adapterAddress=TV,service=DIS,
                values=[{'characteristic':uuid('2a50'),'value':{'bytes':[1,76,0,109,2,0,0]}}])

    def test_firmware_metadata_rejects_malformed_response(self):
        for product, firmware in ((p,fw) for p in (0x0266,0x026d) for fw in (b'',b'\x00',b'x'*129)):
            self.flow.product=product
            with self.assertRaises(ValueError):
                self.reply('identity-firmware',address=REMOTE,adapterAddress=TV,service=DIS,
                    values=[{'characteristic':uuid('2a26'),'value':{'bytes':list(firmware)}}])

    def test_both_models_accept_new_and_unknown_firmware_versions(self):
        for product in (0x0266,0x026d):
            for firmware in (b'0257',b'0118',b'future-revision'):
                with self.subTest(product=product,firmware=firmware):
                    self.flow.product=product;self.flow.pending_serial='TEST_REMOTE'
                    self.flow.existing_only=False
                    self.reply('identity-firmware',address=REMOTE,adapterAddress=TV,service=DIS,
                        values=[{'characteristic':uuid('2a26'),'value':{'bytes':list(firmware)}}])
                    self.assertEqual(self.flow.firmware,firmware.decode('ascii'))
                    self.assertEqual(self.flow.phase,'connecting')
                    self.assertEqual(self.bus.sent[-1][1],'hid/getStatus')


if __name__ == '__main__': unittest.main()
