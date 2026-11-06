import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('installer_tv',Path(__file__).resolve().parents[1]/'tools/installer/tv.py')
tv=importlib.util.module_from_spec(spec);spec.loader.exec_module(tv)

class MaintenanceReceiptTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.app=Path(tmp.name);(self.app/'state').mkdir()
        self.nonce='a'*32;self.file=self.app/'state'/('install-result-'+self.nonce+'.json')
        app=patch.object(tv,'APP_DIR',self.app);app.start();self.addCleanup(app.stop)
        real=os.fstat
        def app_stat(fd):
            value=list(real(fd));value[4]=5982;value[5]=5000
            return os.stat_result(value)
        info=patch.object(tv.os,'fstat',side_effect=app_stat);info.start();self.addCleanup(info.stop)

    def test_unreceived_request_is_distinct_from_pending(self):
        self.assertEqual(tv.maintenance_result(self.nonce),{'status':'not-received'})
        self.file.write_text('{"status":"pending"}');self.file.chmod(0o640)
        self.assertEqual(tv.maintenance_result(self.nonce)['status'],'pending')

    def test_accepted_stop_receipt(self):
        self.file.write_text('{"status":"accepted","action":"stop"}');self.file.chmod(0o640)
        self.assertEqual(tv.maintenance_result(self.nonce),{'status':'accepted','action':'stop','errorText':None})

    def test_invalid_nonce_cannot_read_other_files(self):
        with self.assertRaises(ValueError):tv.maintenance_result('../settings')

    def test_symlink_is_not_followed(self):
        target=self.app/'other';target.write_text('{"status":"accepted"}');self.file.symlink_to(target)
        with self.assertRaises(OSError):tv.maintenance_result(self.nonce)

    def test_invalid_receipt_does_not_acknowledge_stop(self):
        self.file.write_text('{"status":"unexpected"}');self.file.chmod(0o640)
        with self.assertRaisesRegex(RuntimeError,'Invalid maintenance result'):tv.maintenance_result(self.nonce)

if __name__=='__main__':unittest.main()
