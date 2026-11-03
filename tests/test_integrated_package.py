"""Verify one real app/service package, role boundaries and shared runtime pins."""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import build_integrated
import build_support
import runtime_bundle


class BundleRoleTests(unittest.TestCase):
    def child(self, code):
        prefix = 'import sys;sys.path[:0]=' + repr([str(ROOT / 'src/runtime'), str(ROOT / 'src/native'), str(ROOT / 'src/integrated')]) + '\n'
        run = subprocess.run([sys.executable, '-I', '-B', '-c', prefix + code], text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_roles_have_one_application_but_distinct_process_and_state_paths(self):
        for role in ('controller', 'receiver'):
            self.child('''
import runtime_bundle as bundle
bundle.select(''' + repr(role) + ''')
from runtime_device import configure
configure(remote='aa:bb:cc:dd:ee:10',adapter='aa:bb:cc:dd:ee:20',name='Remote')
import resident_controller_entry as controller, postconnect_receiver_native_entry as receiver
import controller_connect_identity as ci, native_app_identity as ni
import receiver_request_auth, receiver_result_receipt, recovery_receipt, tv_launch
from pathlib import Path
assert controller.APP == controller.B == receiver.APP == receiver.CONTROLLER == bundle.APP
assert receiver_request_auth.CONTROLLER == receiver_result_receipt.APP == recovery_receipt.APP == bundle.APP
assert controller.STATE == bundle.ROOT/'roles/controller/state'
assert ci.APP_PATH == str(bundle.ROOT/'roles/controller')
assert ni.APP_PATH == str(bundle.ROOT/'roles/''' + role + '''')
assert tv_launch.APPS['B'] == bundle.APP
assert bundle.role_path('controller','unused') != bundle.role_path('receiver','unused')
try: bundle.select('receiver')
except RuntimeError: pass
else: raise AssertionError('role changed')
''')

    def test_session_authentication_does_not_freeze_device_before_selection(self):
        self.child('''
import runtime_bundle as bundle
bundle.select('receiver')
import bundle_boot, runtime_device
from unittest.mock import patch
record={'process':{'pid':123,'startTicks':456,'status':{'Uid':'6000 6000 6000 6000'}}}
values={'schema':1,'remoteAddress':'aa:bb:cc:dd:ee:10','adapterAddress':'aa:bb:cc:dd:ee:20','remoteName':'Remote'}
found=[{'pid':123,'startTicks':456,'exeVerified':False}]
with patch('controller_start_record.read_record',return_value=record), patch('local_attestation.matching_processes',return_value=found), patch.object(bundle,'read_pin',return_value={}), patch.object(bundle,'package_matches',return_value=True), patch.object(bundle_boot,'_read',return_value=values) as read:
 assert bundle_boot.receiver_settings() == values
 assert read.call_args.args[1] == 6000
 assert read.call_args.args[0].name == '123-456.json'
runtime_device.configure(remote=values['remoteAddress'],adapter=values['adapterAddress'],name=values['remoteName'])
assert runtime_device.identity().name == 'Remote'
''')

    def test_wrong_controller_prevents_loading_session_settings(self):
        self.child('''
import runtime_bundle as bundle
bundle.select('receiver')
import bundle_boot
from unittest.mock import patch
record={'process':{'pid':123,'startTicks':456,'status':{'Uid':'6000 6000 6000 6000'}}}
with patch('controller_start_record.read_record',return_value=record), patch('local_attestation.matching_processes',return_value=[{'pid':123,'startTicks':457}]), patch.object(bundle,'read_pin',return_value={}), patch.object(bundle,'package_matches',return_value=True), patch.object(bundle_boot,'_read') as read:
 try: bundle_boot.receiver_settings()
 except RuntimeError: pass
 else: raise AssertionError('reused pid accepted')
 read.assert_not_called()
''')

    def test_retained_state_cannot_be_rebound_to_another_remote(self):
        self.child("""
import bundle_boot
from unittest.mock import Mock
values={'schema':1,'remoteAddress':'aa:bb:cc:dd:ee:10','adapterAddress':'aa:bb:cc:dd:ee:20','remoteName':'Remote','gyroEnabled':True}
write=Mock(side_effect=FileExistsError)
read=Mock(return_value=values)
bundle_boot.bind_device('/unused',dict(values,gyroEnabled=False),read=read,write=write)
for field,value in [('remoteAddress','aa:bb:cc:dd:ee:30'),('adapterAddress','aa:bb:cc:dd:ee:40'),('remoteName','Other')]:
 try: bundle_boot.bind_device('/unused',dict(values,**{field:value}),read=read,write=write)
 except RuntimeError: pass
 else: raise AssertionError('old journal rebound to different hardware')
""")

    @unittest.skipUnless(shutil.which('clang'), 'Clang required')
    def test_single_package_pins_state_permissions_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = build_integrated.build(base / 'one')
            second = build_integrated.build(base / 'two')
            name = first['package']['package']
            raw = (base / 'one' / name).read_bytes()
            self.assertEqual(raw, (base / 'two' / name).read_bytes())
            parts = build_support.read_ar(raw)
            with tarfile.open(fileobj=io.BytesIO(parts['data.tar.gz']), mode='r:gz') as tar:
                members = {m.name: m for m in tar}
                payload = {name: tar.extractfile(m).read() for name, m in members.items() if m.isfile()}
            apps = [name for name in payload if name.endswith('/appinfo.json')]
            services = [name for name in payload if name.endswith('/services.json')]
            self.assertEqual(len(apps), 1)
            self.assertEqual(len(services), 1)
            prefix = 'usr/palm/services/' + runtime_bundle.SERVICE + '/'
            shared = [name for name in payload if name.endswith('/resident_controller_entry.py')]
            self.assertEqual(shared, [prefix + 'runtime/resident_controller_entry.py'])
            for relative in ('state', 'state/sessions', 'roles/controller/state', 'roles/receiver/state'):
                row = members[prefix + relative]
                self.assertEqual((row.mode, row.uid, row.gid), (0o770, 5999, 5000))
            for relative, data in payload.items():
                target = base / 'unpacked' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                if relative.endswith('.py'):
                    compile(data, relative, 'exec')
            service = base / 'unpacked' / prefix
            package = base / 'unpacked/usr/palm/packages' / runtime_bundle.APP
            for role in ('controller', 'receiver'):
                pin = json.loads((service / 'pins' / (role + '.json')).read_text())
                self.assertTrue(runtime_bundle.package_matches(service / 'roles' / role, package, pin))
                other = 'controller' if role == 'receiver' else 'receiver'
                self.assertFalse(runtime_bundle.package_matches(service / 'roles' / other, package, pin))
                code = service / 'runtime/borrowed_mode_writer.py'
                original = code.read_bytes(); code.write_bytes(original + b'\n# changed\n')
                self.assertFalse(runtime_bundle.package_matches(service / 'roles' / role, package, pin))
                code.write_bytes(original)
            # Package manager metadata is hidden in the real service jail.
            # Code attestation uses the actual installed service metadata.
            (package / 'packageinfo.json').unlink()
            self.assertTrue(runtime_bundle.package_matches(service / 'roles' / role, package, pin))
            metadata = service / 'package.json'
            metadata.write_text('{"name":"wrong.service"}')
            self.assertFalse(runtime_bundle.package_matches(service / 'roles' / role, package, pin))
            # Runtime packaging is not a claim of activation or device validation.
            self.assertTrue(first['runtimeActivationAvailable'])
            self.assertFalse(first['hardwareValidated'])
            self.assertFalse(first['registersAutomaticStartup'])


if __name__ == '__main__':
    unittest.main()
