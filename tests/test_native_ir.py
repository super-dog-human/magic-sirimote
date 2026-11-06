import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/native'), str(ROOT / 'src')]
import ir_programmer as ir
from ir_screen import InfraredScreen, PRESETS, CHOICES, CUSTOM

A1513_FIRMWARE = b'01004102200070033000070131001800B000410240001508'
A1962_FIRMWARE = b'B000750001001601300030022000040431001800C1000100'
FIRMWARE_CHARACTERISTIC = '00002a26-0000-1000-8000-00805f9b34fb'

VALUES = {'schema': 1, 'remoteAddress': '02:aa:bb:cc:dd:01',
          'adapterAddress': '02:aa:bb:cc:dd:02', 'remoteName': 'TEST_REMOTE'}


class TV:
    """Realistic LS2 response shapes with injected identity and delivery failures."""
    def __init__(self):
        self.calls = []
        self.firmware = A1513_FIRMWARE
        self.pnp = bytes.fromhex("014c0066020000")
        self.mode = b'\xa0\x00'
        self.serial = b'TEST_REMOTE'
        self.fail_write = False
        self.wrong_adapter = False
        self.reference = b'\xf0\x03'

    def __call__(self, method, params, timeout):
        self.calls.append((method, params))
        answer = {'returnValue': True, 'address': VALUES['remoteAddress'],
                  'adapterAddress': '02:aa:bb:cc:dd:03' if self.wrong_adapter else VALUES['adapterAddress']}
        if method.endswith('/getStatus'):
            answer.update(connected=True, connecting=False, connectRequest=False)
        elif method == 'gatt/connect':
            answer['clientId'] = '005'
        elif method == 'gatt/readCharacteristicValues':
            char = params['characteristics'][0]
            answer['service'] = params['service']
            data = {ir.SERIAL: self.serial, FIRMWARE_CHARACTERISTIC: self.firmware, ir.REPORT: self.mode, ir.PNP: self.pnp}[char]
            answer['values'] = [{'characteristic': char, 'instanceId': '029', 'value': {'bytes': list(data)}}]
        elif method == 'gatt/readDescriptorValues':
            answer['service'] = ir.HID
            answer['values'] = [{'descriptor': ir.REFERENCE, 'value': {'bytes': list(self.reference)}}]
        elif method == 'hid/internal/setReport' and params['reportData'][1] in (1, 2, 128) and self.fail_write:
            raise TimeoutError('delivery unknown')
        return answer

    def writes(self):
        return [p['reportData'] for m, p in self.calls
                if m == 'hid/internal/setReport' and p['reportData'][1] in (1, 2, 128)]


class InfraredTest(unittest.TestCase):
    def test_lg_codes_match_observed_wire_packets(self):
        for button, code, wire in ((2, '02', '20df40bf'), (4, '03', '20dfc03f'),
                                   (1, '08', '20df10ef'), (32, '43', '20dfc23d')):
            self.assertEqual(ir.packet('set', button, 0, code).hex(), 'f001%02x00010000000000%s' % (button, wire))
        self.assertEqual(ir.packet('delete', 16, 0), bytes.fromhex('f0021000'))
        self.assertEqual(ir.packet('delete', 1, 2), bytes.fromhex('f0020102'))

    def test_invalid_request_never_opens_transport(self):
        for args in [('set', 1, 0, ''), ('set', 1, 0, 'GG'), ('set', 3, 0, '02'),
                     ('delete', 1, -1, ''), ('delete', True, 0, ''), ('set', 1, 256, '02')]:
            tv = TV()
            with self.subTest(args=args), self.assertRaises(ValueError):
                ir.program(VALUES, *args, tv, lambda x: None, idle=lambda: None)
            self.assertEqual(tv.calls, [])

    def test_only_selected_entry_is_sent_and_receipt_precedes_write(self):
        for action in ('set', 'delete'):
            tv = TV(); records = []
            def call(*args):
                if args[0] == 'hid/internal/setReport' and args[1]['reportData'][1] in (1, 2, 128):
                    self.assertEqual(records[-1]['status'], 'pending')
                return tv(*args)
            result = ir.program(VALUES, action, 1, 2, '08', call, records.append, idle=lambda: None)
            self.assertEqual(tv.writes(), [list(ir.packet(action, 1, 2, '08'))])
            self.assertEqual(result['status'], 'submitted')
            self.assertFalse(result['readbackVerified'])
            self.assertTrue(result['connectionPreserved'])
            self.assertFalse(any(m == 'gatt/disconnect' for m, _ in tv.calls))
            self.assertFalse(any(m in ('hid/disconnect', 'device/pair') for m, p in tv.calls))

    def test_two_assignments_keep_the_preexisting_input_connection(self):
        tv=TV();connected=True
        def call(method,params,timeout):
            nonlocal connected
            if method=='gatt/disconnect':connected=False
            if not connected:return {'returnValue':False}
            return tv(method,params,timeout)
        for button,code in ((16,'09'),(32,'43')):
            result=ir.program(VALUES,'set',button,0,code,call,lambda _:None,idle=lambda:None)
            self.assertEqual(result['status'],'submitted')
            self.assertTrue(result['connectionPreserved'])
        self.assertTrue(connected)
        self.assertEqual(len(tv.writes()),2)

    def test_bad_identity_active_sensor_or_report_blocks_write(self):
        for field, value in [('serial', b'OTHER'), ('mode', b'\xa0\x01'),
                             ('reference', b'\xf1\x03'), ('wrong_adapter', True)]:
            tv = TV(); setattr(tv, field, value)
            result = ir.program(VALUES, 'set', 2, 0, '02', tv, lambda x: None, idle=lambda: None)
            self.assertEqual(result['status'], 'not-sent', field)
            self.assertEqual(tv.writes(), [], field)

    def test_validated_a1962_can_set_and_delete_one_assignment(self):
        for action in ('set', 'delete'):
            tv=TV();tv.pnp=bytes.fromhex('014c006d020000');tv.firmware=A1962_FIRMWARE
            result=ir.program(VALUES,action,16,0,'09',tv,lambda _:None,idle=lambda:None)
            self.assertEqual(result['status'],'submitted')
            self.assertEqual(tv.writes(),[list(ir.packet(action,16,0,'09'))])

    def test_unsupported_product_blocks_any_feature_write(self):
        for pnp in (bytes.fromhex('014c006e020000'), bytes.fromhex('014d006d020000'),
                    bytes.fromhex('024c006d020000'), b''):
            tv=TV();tv.pnp=pnp
            result=ir.program(VALUES,'set',16,0,'09',tv,lambda _:None,idle=lambda:None)
            self.assertEqual(result['status'],'not-sent')
            self.assertFalse(any(m=='hid/internal/setReport' for m,_ in tv.calls))

    def test_every_revision_can_program_supported_models_without_firmware_read(self):
        for product in (0x0266, 0x026d):
            for action in ('set', 'delete', 'reset-all'):
                with self.subTest(product=product, action=action):
                    tv=TV();tv.pnp=b'\x01\x4c\x00'+product.to_bytes(2,'little')+b'\xff\xff'
                    def call(method,params,timeout):
                        if method=='gatt/readCharacteristicValues':
                            self.assertNotIn(FIRMWARE_CHARACTERISTIC,params['characteristics'])
                        return tv(method,params,timeout)
                    button,delay,code=(None,None,'') if action=='reset-all' else (16,0,'09')
                    result=ir.program(VALUES,action,button,delay,code,call,lambda _:None,idle=lambda:None)
                    self.assertEqual(result['status'],'submitted')
                    self.assertEqual(tv.writes(),[list(ir.packet(action,button,delay,code))])

    def test_uncertain_write_is_never_retried_or_rolled_back(self):
        tv = TV(); tv.fail_write = True
        result = ir.program(VALUES, 'delete', 1, 2, '', tv, lambda x: None, idle=lambda: None)
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(tv.writes(), [[240, 2, 1, 2]])

    def test_bulk_reset_is_one_guarded_request_for_each_validated_remote(self):
        for pnp,fw in ((bytes.fromhex('014c0066020000'),A1513_FIRMWARE),
                       (bytes.fromhex('014c006d020000'),A1962_FIRMWARE)):
            tv=TV();tv.pnp=pnp;tv.firmware=fw
            result=ir.program(VALUES,'reset-all',None,None,'',tv,lambda _:None,idle=lambda:None)
            self.assertEqual(result['status'],'submitted')
            self.assertEqual(tv.writes(),[[240,128,170,85]])
            tv=TV();tv.pnp=pnp;tv.firmware=fw;tv.fail_write=True
            result=ir.program(VALUES,'reset-all',None,None,'',tv,lambda _:None,idle=lambda:None)
            self.assertEqual(result['status'],'uncertain')
            self.assertEqual(tv.writes(),[[240,128,170,85]])
        for button,delay,code in ((1,None,''),(None,0,''),(None,None,'09')):
            with self.assertRaises(ValueError):ir.packet('reset-all',button,delay,code)

    def test_bulk_reset_receipts_clear_or_invalidate_all_prior_ir_knowledge(self):
        import json,os,tv_assignments
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ir-operation-reset.json'
            known={'01:00':'ir:7C','01:02':'ir:08','10:00':'ir:09'}
            for status in ('submitted','pending','uncertain'):
                path.write_text(json.dumps({'status':status,'action':'reset-all','button':None,'delay':None,'code':None}))
                value=tv_assignments.ir_knowledge(d,known)
                self.assertEqual(value, {tv_assignments.slot(b,t):'none' for _,b in ir.BUTTONS for t in (0,2)} if status=='submitted' else {})
            path.write_text(json.dumps({'status':'submitted','action':'reset-all','button':None,'delay':None,'code':None}))
            os.utime(path,ns=(1,1))
            (Path(d)/'ir-operation-new.json').write_text(json.dumps({'status':'submitted','action':'set','button':16,'delay':0,'code':'09'}))
            self.assertEqual(tv_assignments.ir_knowledge(d,known)['10:00'],'ir:09')

    def test_running_runtime_blocks_all_device_access(self):
        tv = TV()
        def busy(): raise RuntimeError('Stop the input runtime first.')
        result = ir.program(VALUES, 'delete', 16, 0, '', tv, lambda x: None, idle=busy)
        self.assertEqual(result['status'], 'not-sent')
        self.assertEqual(tv.calls, [])

    def test_record_failure_before_pending_prevents_persistent_write(self):
        tv = TV()
        def record(value):
            if value['status'] == 'pending': raise OSError('disk full')
        result = ir.program(VALUES, 'set', 2, 0, '02', tv, record, idle=lambda: None)
        self.assertEqual(result['status'], 'not-sent')
        self.assertEqual(tv.writes(), [])

    def test_none_is_staged_and_back_preserves_it_without_saving(self):
        with tempfile.TemporaryDirectory() as d:
            drafts={};app=InfraredScreen(Path(d),drafts=drafts)
            app.choose(0);app.choose(0);app.handle(('key',27))
            self.assertTrue(app.done);self.assertEqual(drafts,{'20:00':'none'})
            self.assertEqual(list(Path(d).iterdir()),[])
            self.assertIn('(edited)',InfraredScreen(Path(d),drafts=drafts).cell_label(32,0))

    def test_preset_and_custom_choices_only_update_the_draft(self):
        with tempfile.TemporaryDirectory() as d:
            app=InfraredScreen(Path(d))
            app.choose(0);app.choose(next(i for i,(_,v) in enumerate(CHOICES) if v=='ir:28'))
            self.assertEqual(app.drafts,{'20:00':'ir:28'})
            app.choose(0);app.choose(CUSTOM);app.handle(('text','g4'));app.choose(17)
            self.assertTrue(app.editing);app.handle(('text','d'));app.choose(17)
            self.assertEqual(app.drafts,{'20:00':'ir:4D'})
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_cancel_custom_code_preserves_previous_selection(self):
        app=InfraredScreen(Path('/unused'))
        app.choose(0);app.choose(CUSTOM);app.handle(('text','08'));app.handle(('key',27))
        self.assertTrue(app.done);self.assertFalse(app.editing);self.assertEqual(app.code,'')


    def test_all_buttons_and_press_types_send_only_the_selected_entry(self):
        # Transport still supports all seven physical bits, including surface click.
        for name,mask in ir.BUTTONS:
            for delay in (0,2):
                for action in ('set','delete'):
                    with self.subTest(button=name,delay=delay,action=action):
                        tv=TV();result=ir.program(VALUES,action,mask,delay,'08',tv,lambda r:None,idle=lambda:None)
                        self.assertEqual(result['status'],'submitted')
                        wire=([240,1,mask,delay,1,0,0,0,0,0,32,223,16,239] if action=='set' else [240,2,mask,delay])
                        self.assertEqual(tv.writes(),[wire])


    def test_button_and_press_picker_navigation_and_cancel(self):
        app=InfraredScreen(Path('/unused'))
        app.handle(('key',1073741905));self.assertEqual(app.focus,2)
        app.handle(('key',1073741903));app.handle(('key',13))
        self.assertEqual(app.button,1);self.assertEqual(app.delay,2)
        self.assertTrue(app.picking);app.handle(('key',27));self.assertTrue(app.done)


    def test_reselecting_saved_choice_clears_pending_edit(self):
        import tv_assignments
        with tempfile.TemporaryDirectory() as d:
            tv_assignments.execute(d,'assign',32,0,'playpause')
            app=InfraredScreen(Path(d));app.choose(0);app.choose(0)
            self.assertTrue(app.drafts)
            app.choose(0);app.choose(next(i for i, item in enumerate(CHOICES) if item[1]=='playpause'))
            self.assertFalse(app.drafts)
            self.assertEqual(tv_assignments.load(d)['bindings'],{'20:00':'playpause'})


if __name__ == '__main__':
    unittest.main()
