"""Root cleanup is exercised with isolated files and a simulated service."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('guard_remove',Path(__file__).resolve().parents[1]/'tools/installer/guard_remove.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)

class GuardRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)/'guard';self.env=Path(self.temp.name)/'bthidmanager.env'
        self.lib=self.base/'libsirimote-hid-guard.so';self.record=self.base/'installed.json';self.rollback=self.base/'rollback.py'
        changes=patch.multiple(guard,BASE=self.base,ENV=self.env,LIB=self.lib,RECORD=self.record,ROLLBACK=self.rollback)
        changes.start();self.addCleanup(changes.stop)
        uid=patch.object(guard.os,'geteuid',return_value=0);uid.start();self.addCleanup(uid.stop)
        original=Path.lstat
        def root_stat(p,*args,**kwargs):
            values=list(original(p,*args,**kwargs));values[4]=0
            return os.stat_result(values)
        mockstat=patch.object(Path,'lstat',autospec=True,side_effect=root_stat);mockstat.start();self.addCleanup(mockstat.stop)

    def installed(self):
        self.base.mkdir(mode=0o755)
        self.lib.write_bytes(b'library');self.rollback.write_bytes(b'rollback')
        self.env.write_text('LD_PRELOAD='+str(self.lib)+'\n')
        value={'version':1,'environmentFile':str(self.env),'environmentContent':self.env.read_text(),
               'librarySha256':hashlib.sha256(self.lib.read_bytes()).hexdigest(),
               'rollbackSha256':hashlib.sha256(self.rollback.read_bytes()).hexdigest(),
               'createdDirectories':[]}
        self.record.write_text(json.dumps(value))
        for p in (self.lib,self.rollback,self.env,self.record):p.chmod(0o600)
        return value

    def test_absent_fix_does_not_restart_service(self):
        with patch.object(guard,'service') as service,patch.object(guard.subprocess,'run') as run:
            self.assertEqual(guard.dispatch('remove'),{'state':'absent'})
            service.assert_not_called();run.assert_not_called()

    def test_root_is_required_even_when_files_look_absent(self):
        with patch.object(guard.os,'geteuid',return_value=5415):
            with self.assertRaisesRegex(RuntimeError,'Root SSH'):guard.inspect()

    def test_original_v1_record_is_recognized(self):
        self.installed();self.assertEqual(guard.inspect(),{'state':'installed'})

    def test_partial_install_is_not_mistaken_for_absence(self):
        self.env.write_text('LD_PRELOAD=old\n')
        with self.assertRaisesRegex(RuntimeError,'incomplete'):guard.inspect()
        self.assertTrue(self.env.exists())

    def test_modified_library_is_not_removed(self):
        self.installed();self.lib.write_text('modified')
        with patch.object(guard.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'differ'):guard.dispatch('remove')
            run.assert_not_called()
        self.assertTrue(self.lib.exists())

    def test_symlinked_environment_is_not_followed(self):
        self.installed();self.env.unlink();self.env.symlink_to(self.lib)
        with self.assertRaisesRegex(RuntimeError,'ownership/type'):guard.inspect()

    def test_unexpected_cleanup_directories_are_rejected(self):
        value=self.installed();value['createdDirectories']=['/another/app'];self.record.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError,'directory record'):guard.inspect()

    def test_success_removes_empty_directory_and_verifies_service(self):
        self.installed()
        def remove(*args,**kwargs):
            for p in (self.env,self.lib,self.record,self.rollback):p.unlink()
        with patch.object(guard,'service',side_effect=[{'MainPID':'10'},{'MainPID':'11'}]), \
             patch.object(guard.subprocess,'run',side_effect=remove), \
             patch.object(Path,'read_text',return_value='stock maps'):
            result=guard.dispatch('remove')
        self.assertEqual(result,{'state':'removed','tvRebooted':False})
        self.assertFalse(self.base.exists());self.assertEqual(guard.dispatch('remove'),{'state':'absent'})

    def test_rollback_failure_does_not_report_success(self):
        self.installed()
        with patch.object(guard,'service',return_value={'MainPID':'10'}), \
             patch.object(guard.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['rollback'])):
            with self.assertRaises(subprocess.CalledProcessError):guard.dispatch('remove')
        self.assertTrue(self.lib.exists())

    def test_still_mapped_library_is_not_reported_as_removed(self):
        self.installed()
        def remove(*args,**kwargs):
            for p in (self.env,self.lib,self.record,self.rollback):p.unlink()
        with patch.object(guard,'service',side_effect=[{'MainPID':'10'},{'MainPID':'11'}]), \
             patch.object(guard.subprocess,'run',side_effect=remove), \
             patch.object(Path,'read_text',return_value=str(self.lib)):
            with self.assertRaisesRegex(RuntimeError,'still needs attention'):guard.dispatch('remove')

if __name__=='__main__':unittest.main()
