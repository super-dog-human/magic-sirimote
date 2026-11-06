import base64
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('temporary_tv', ROOT/'tools/installer/temporary_tv.py')
tv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tv)
runner_spec = importlib.util.spec_from_file_location('temporary_runner', ROOT/'tools/installer/temporary_runner.py')
runner = importlib.util.module_from_spec(runner_spec)
runner_spec.loader.exec_module(runner)


class TemporaryFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(tv, 'PARENT', Path(self.temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.run_id = 'a'*24

    def stage(self):
        return tv.dispatch({'action':'stage', 'run':self.run_id,
            'files':{name:base64.b64encode(b'content').decode() for name in tv.FILES[:4]}})

    def test_stage_inventory_and_exact_cleanup(self):
        result = self.stage()
        self.assertEqual(set(result['hashes']), set(tv.FILES[:4]))
        self.assertEqual(tv.dispatch({'action':'list'}), {'runs':[self.run_id]})
        self.assertEqual(tv.dispatch({'action':'report','run':self.run_id}), {'pending':True})
        self.assertEqual(tv.dispatch({'action':'cleanup','run':self.run_id}), {'removed':True})
        self.assertEqual(tv.dispatch({'action':'list'}), {'runs':[]})

    def test_does_not_overwrite_previous_staging(self):
        self.stage()
        with self.assertRaises(FileExistsError): self.stage()

    def test_rejects_path_and_directory_symlink(self):
        with self.assertRaises(ValueError): tv.directory('../outside', exists=False)
        base = tv.directory(self.run_id, exists=False)
        base.symlink_to(self.temp.name)
        with self.assertRaises(RuntimeError): tv.dispatch({'action':'cleanup','run':self.run_id})

    def test_never_follows_replaced_manifest_directory(self):
        self.stage()
        base = tv.directory(self.run_id)
        (base/'manifests/probe.json').unlink()
        (base/'manifests').rmdir()
        (base/'manifests').symlink_to(self.temp.name)
        with self.assertRaises(RuntimeError): tv.dispatch({'action':'cleanup','run':self.run_id})
        self.assertTrue((base/'runner.py').exists())

    def test_unknown_file_prevents_claiming_cleanup_success(self):
        self.stage()
        (tv.directory(self.run_id)/'unexpected').write_text('keep')
        with self.assertRaises(OSError): tv.dispatch({'action':'cleanup','run':self.run_id})

    def test_report_rejects_symlink_and_returns_owner(self):
        self.stage()
        p = tv.directory(self.run_id)/'report.json'
        p.write_text(json.dumps({'result':{'state':'absent'}}))
        self.assertEqual(tv.dispatch({'action':'report','run':self.run_id})['owner'], os.getuid())
        p.unlink();p.symlink_to('/etc/passwd')
        with self.assertRaises(OSError): tv.dispatch({'action':'report','run':self.run_id})

    def run_payload(self, source, uid=0):
        self.stage()
        base = tv.directory(self.run_id)
        (base/'operation.py').write_text(source)
        boot = Path(self.temp.name)/'boot'
        boot.write_text('test-boot')
        def paths(value):
            return boot if str(value) == '/proc/sys/kernel/random/boot_id' else Path(value)
        with patch.object(runner, 'Path', paths), patch.object(runner.os, 'geteuid', return_value=uid), \
                patch.object(runner.signal, 'signal'), patch.object(runner.signal, 'alarm'):
            runner.execute(base, self.run_id)
        return json.loads((base/'report.json').read_text())

    def test_payload_cannot_replace_receipt_scope(self):
        data = self.run_payload("base='/wrong-path'\nrun='wrong'\nreport={}\nresult={'state':'absent'}")
        self.assertEqual(data['run'], self.run_id)
        self.assertEqual(data['result'], {'state':'absent'})
        self.assertTrue(data['sameBoot'])
        self.assertFalse((tv.directory(self.run_id)/'report.pending').exists())

    def test_nonroot_never_runs_operation(self):
        data = self.run_payload("raise RuntimeError('must not execute')", uid=5000)
        self.assertIn('unavailable', data['error'])
        self.assertNotIn('must not execute', data['error'])

    def test_expired_service_cannot_claim_or_execute(self):
        self.stage()
        base = tv.directory(self.run_id)
        stamp = time.time() - 30
        os.utime(base/'runner.py', (stamp, stamp))
        with self.assertRaisesRegex(RuntimeError, 'expired'): runner.execute(base, self.run_id)
        self.assertFalse((base/'claimed').exists())


if __name__ == '__main__': unittest.main()
