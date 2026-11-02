import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/native'), str(ROOT / 'src')]
import ir_programmer as ir
from ir_screen import InfraredScreen, PRESETS

VALUES = {'schema': 1, 'remoteAddress': '02:aa:bb:cc:dd:01',
          'adapterAddress': '02:aa:bb:cc:dd:02', 'remoteName': 'TEST_REMOTE'}


class TV:
    """Realistic LS2 response shapes with injected identity and delivery failures."""
    def __init__(self):
        self.calls = []
        self.firmware = ir.SUPPORTED_FIRMWARE
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
            data = {ir.SERIAL: self.serial, ir.FIRMWARE: self.firmware, ir.REPORT: self.mode}[char]
            answer['values'] = [{'characteristic': char, 'instanceId': '029', 'value': {'bytes': list(data)}}]
        elif method == 'gatt/readDescriptorValues':
            answer['service'] = ir.HID
            answer['values'] = [{'descriptor': ir.REFERENCE, 'value': {'bytes': list(self.reference)}}]
        elif method == 'hid/internal/setReport' and params['reportData'][1] in (1, 2) and self.fail_write:
            raise TimeoutError('delivery unknown')
        return answer

    def writes(self):
        return [p['reportData'] for m, p in self.calls
                if m == 'hid/internal/setReport' and p['reportData'][1] in (1, 2)]


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
                if args[0] == 'hid/internal/setReport' and args[1]['reportData'][1] in (1, 2):
                    self.assertEqual(records[-1]['status'], 'pending')
                return tv(*args)
            result = ir.program(VALUES, action, 1, 2, '08', call, records.append, idle=lambda: None)
            self.assertEqual(tv.writes(), [list(ir.packet(action, 1, 2, '08'))])
            self.assertEqual(result['status'], 'submitted')
            self.assertFalse(result['readbackVerified'])
            self.assertTrue(result['clientReleased'])
            self.assertIn(('gatt/disconnect', {'clientId': '005'}), tv.calls)
            self.assertFalse(any(m in ('hid/disconnect', 'device/pair') for m, p in tv.calls))

    def test_bad_identity_firmware_active_sensor_or_report_blocks_write(self):
        for field, value in [('serial', b'OTHER'), ('firmware', b'OTHER'), ('mode', b'\xa0\x01'),
                             ('reference', b'\xf1\x03'), ('wrong_adapter', True)]:
            tv = TV(); setattr(tv, field, value)
            result = ir.program(VALUES, 'set', 2, 0, '02', tv, lambda x: None, idle=lambda: None)
            self.assertEqual(result['status'], 'not-sent', field)
            self.assertEqual(tv.writes(), [], field)

    def test_uncertain_write_is_never_retried_or_rolled_back(self):
        tv = TV(); tv.fail_write = True
        result = ir.program(VALUES, 'delete', 1, 2, '', tv, lambda x: None, idle=lambda: None)
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(tv.writes(), [[240, 2, 1, 2]])

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

    def test_confirmation_cancel_and_delete_without_a_code(self):
        calls = []
        app = InfraredScreen(Path('/unused'), submit=lambda *a: calls.append(a))
        app.choose(4)
        self.assertEqual(app.review, 'delete')
        self.assertEqual(calls, [])
        app.handle(('key', 27))
        self.assertIsNone(app.review)
        self.assertEqual(calls, [])
        app.choose(3)  # Set needs a code; Delete does not.
        self.assertIsNone(app.review)

    def test_preset_and_custom_selection_do_not_send_until_confirmed(self):
        calls = []
        app = InfraredScreen(Path('/unused'), submit=lambda *args: calls.append(args))
        app.choose(2)
        app.choose(next(i for i, (name, code) in enumerate(PRESETS) if name == 'Back'))
        self.assertEqual(app.code, '28')
        self.assertFalse(app.picking)
        app.choose(2); app.choose(len(PRESETS))
        app.choose(16); app.choose(16)  # Erase the selected preset.
        app.handle(('text', 'g4'))  # Ignore non-hexadecimal characters.
        app.choose(17)
        self.assertTrue(app.editing)  # Incomplete codes cannot be accepted.
        app.handle(('text', 'd'))
        app.choose(17)
        self.assertEqual(app.code, '4D')
        self.assertFalse(app.editing)
        app.choose(3)
        self.assertEqual(app.review, 'set')
        self.assertEqual(calls, [])
        app.choose(0)
        self.assertEqual(calls, [])

    def test_cancel_custom_code_preserves_previous_selection(self):
        app = InfraredScreen(Path('/unused'))
        app.choose(2); app.choose(0)
        self.assertEqual(app.code, '08')
        app.choose(2); app.choose(len(PRESETS))
        app.choose(16)
        app.handle(('key', 27))
        self.assertTrue(app.picking)
        app.handle(('key', 27))
        self.assertFalse(app.picking)
        self.assertEqual(app.code, '08')
        self.assertFalse(app.done)

    def test_all_buttons_and_press_types_send_only_the_selected_entry(self):
        expected = [('TV / Home', 1), ('Volume +', 2), ('Volume -', 4),
                    ('Play / Pause', 8), ('Microphone', 16), ('MENU', 32),
                    ('Surface click', 128)]
        self.assertEqual(list(ir.BUTTONS), expected)
        for index, (name, mask) in enumerate(expected):
            for press, delay in ((0, 0), (1, 2)):
                for action, control in (('set', 3), ('delete', 4)):
                    with self.subTest(button=name, delay=delay, action=action):
                        tv = TV()
                        def submit(state, action, button, delay, code):
                            return ir.program(VALUES, action, button, delay, code,
                                              tv, lambda record: None, idle=lambda: None)
                        app = InfraredScreen(Path('/unused'), submit=submit)
                        app.choose(0); app.choose(index)
                        app.choose(1); app.choose(press)
                        app.choose(2); app.choose(0)  # Power on/off, 08.
                        self.assertEqual(tv.calls, [])
                        app.choose(control)
                        self.assertEqual(tv.calls, [])
                        app.choose(1)
                        result = app.results.get(timeout=2)
                        self.assertEqual(result['status'], 'submitted')
                        wire = ([240, 1, mask, delay, 1, 0, 0, 0, 0, 0, 32, 223, 16, 239]
                                if action == 'set' else [240, 2, mask, delay])
                        self.assertEqual(tv.writes(), [wire])

    def test_button_and_press_picker_navigation_and_cancel(self):
        app = InfraredScreen(Path('/unused'))
        app.choose(0)
        app.handle(('key', 1073741905))  # Down one row in a two-column list.
        self.assertEqual(app.focus, 2)
        app.handle(('key', 13))
        self.assertEqual(app.button, 2)
        app.choose(0)
        self.assertEqual(app.focus, 2)
        app.handle(('key', 27))
        self.assertEqual(app.button, 2)
        self.assertIsNone(app.selecting)
        self.assertFalse(app.done)
        app.choose(1)
        app.handle(('key', 1073741905))
        app.handle(('key', 13))
        self.assertEqual(app.delay, 2)
        app.choose(1)
        self.assertEqual(app.focus, 1)
        app.choose(2)  # Explicit Cancel.
        self.assertEqual(app.delay, 2)
        self.assertEqual(app.focus, 1)
        self.assertIsNone(app.selecting)

    def test_confirm_runs_once_and_busy_ignores_repeated_input(self):
        import threading
        entered = threading.Event(); release = threading.Event(); calls = []
        def submit(*args):
            calls.append(args); entered.set(); release.wait(2)
            return {'status': 'submitted'}
        app = InfraredScreen(Path('/unused'), submit=submit)
        app.choose(4); app.choose(1)
        self.assertTrue(entered.wait(1))
        app.choose(1); app.handle(('key', 27))
        self.assertFalse(app.done)
        self.assertEqual(len(calls), 1)
        release.set()
        # Wait for the worker result without issuing any second transaction.
        result = app.results.get(timeout=2); app.results.put(result)
        self.assertTrue(app.tick())
        self.assertFalse(app.busy)
        self.assertIn('not been read back', app.detail)


if __name__ == '__main__':
    unittest.main()
