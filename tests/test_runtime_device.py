"""Exercise runtime-wide device selection in independent launcher processes."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / 'src/runtime'


class RuntimeDeviceTests(unittest.TestCase):
    def run_child(self, code):
        result = subprocess.run([sys.executable, '-I', '-B', '-c',
                                 'import sys;sys.path.insert(0,' + repr(str(RUNTIME)) + ')\n' + code],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_selection_reaches_reads_input_guards_start_stop_and_recovery(self):
        self.run_child('''
import runtime_device as device
from dataclasses import FrozenInstanceError
device.configure(remote='AA:BB:CC:DD:EE:10',adapter='AA:BB:CC:DD:EE:20',name='Remote_123')
import tv_bluetooth, hid_input, borrowed_gatt_view, input_notifications
import direct_gatt_read, persistent_status_client, resident_autoconnect, lifecycle
import bootstrap_connect, idle_recovery, borrowed_mode_writer
for module in (tv_bluetooth, hid_input, borrowed_gatt_view, input_notifications,
               direct_gatt_read, persistent_status_client):
 assert module.TARGET == 'aa:bb:cc:dd:ee:10', module
for module in (tv_bluetooth, borrowed_gatt_view, input_notifications, direct_gatt_read):
 assert module.ADAPTER == 'aa:bb:cc:dd:ee:20', module
assert tv_bluetooth.NAME == hid_input.NAME == resident_autoconnect.NAME == 'Remote_123'
assert lifecycle.REMOTE == 'aa:bb:cc:dd:ee:10'
assert lifecycle.ADAPTER == 'aa:bb:cc:dd:ee:20'
import json
assert json.loads(idle_recovery.EXPECTED)['address'] == 'aa:bb:cc:dd:ee:10'
assert bootstrap_connect.connect_intent() == idle_recovery.EXPECTED
calls=[]
class Client:
 def __call__(self, method, params, **kwargs):
  calls.append((method,params));return {'returnValue':True}
writer=borrowed_mode_writer.BorrowedModeWriter(Client(),Client(),guard=lambda:True)
writer.permit_enable();writer(1);writer(0)
assert [p['address'] for _,p in calls] == ['aa:bb:cc:dd:ee:10'] * 2
assert [p['reportData'] for _,p in calls] == [[240,160,1],[240,160,0]]
try: device.identity().remote = 'something-else'
except FrozenInstanceError: pass
else: raise AssertionError('mutable identity')
try: device.configure(remote='aa:bb:cc:dd:ee:30',adapter='aa:bb:cc:dd:ee:20',name='Other')
except RuntimeError: pass
else: raise AssertionError('active identity switched')
''')

    def test_legacy_durable_intent_is_byte_compatible(self):
        raw = self.run_child('import runtime_device;print(runtime_device.connect_intent().hex())')
        self.assertEqual(bytes.fromhex(raw.strip()),
                         b'{"schema":1,"method":"hid/connect","address":"02:00:00:00:00:01","outcome":"reserved-possibly-dispatched"}\n')

    def test_late_configuration_fails_before_splitting_consumers(self):
        self.run_child('''
import hid_input
import runtime_device
try: runtime_device.configure(remote='aa:bb:cc:dd:ee:10',adapter='aa:bb:cc:dd:ee:20',name='Remote')
except RuntimeError: pass
else: raise AssertionError('late configuration accepted')
import tv_bluetooth
assert hid_input.TARGET == tv_bluetooth.TARGET
''')

    def test_invalid_values_do_not_change_or_consume_selection(self):
        self.run_child('''
import runtime_device as d
base=dict(remote='aa:bb:cc:dd:ee:10',adapter='aa:bb:cc:dd:ee:20',name='Remote')
for field,value in [('remote','00:00:00:00:00:00'),('remote','ff:ff:ff:ff:ff:ff'),
 ('remote','aa:bb:cc:dd:ee:20'),('remote',True),('name','bad/name'),('name',''),
 ('adapter','aa:bb:cc:dd:ee:20\\n')]:
 try: d.configure(**dict(base,**{field:value}))
 except ValueError: pass
 else: raise AssertionError((field,value))
d.configure(**base)
try: d.configure(**base)
except RuntimeError: pass
else: raise AssertionError('second selection accepted')
assert d.identity().name == 'Remote'
''')


if __name__ == '__main__':
    unittest.main()
