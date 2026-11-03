import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/native'), str(ROOT / 'src')]
import tv_assignments as tv
from ir_screen import InfraredScreen, PRESETS


class TVAssignmentsTest(unittest.TestCase):
    def test_save_reload_delete_only_selected_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            for button, delay in ((16, 0), (16, 2), (32, 0)):
                result = tv.execute(folder, 'set', button, delay)
                self.assertEqual(result['status'], 'configured-only')
                self.assertFalse(result['active'])
            self.assertEqual(tv.load(folder)['bindings'], {
                '10:00': 'screen-toggle', '10:02': 'screen-toggle', '20:00': 'screen-toggle'})
            tv.execute(folder, 'delete', 16, 0)
            self.assertEqual(tv.load(folder)['bindings'], {
                '10:02': 'screen-toggle', '20:00': 'screen-toggle'})
            self.assertEqual((Path(folder) / tv.FILE).stat().st_mode & 0o777, 0o600)

    def test_invalid_or_symlinked_storage_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / tv.FILE
            for raw in ['{"schema":1,"bindings":{"10:00":"power-off"}}',
                        '{"schema":1,"bindings":{},"bindings":{}}']:
                file.write_text(raw)
                with self.assertRaises(ValueError): tv.execute(folder, 'set', 16, 0)
                self.assertEqual(file.read_text(), raw)
            file.unlink()
            target = Path(folder) / 'target'; target.write_text('unchanged')
            file.symlink_to(target)
            with self.assertRaises(OSError): tv.execute(folder, 'set', 16, 0)
            self.assertTrue(file.is_symlink())
            self.assertEqual(target.read_text(), 'unchanged')

    def test_screen_choice_is_staged_before_explicit_assignment(self):
        calls=[]
        with tempfile.TemporaryDirectory() as folder:
            def program(*args):
                calls.append(args)
                return {'status':'submitted','clientReleased':True,'receiptSaved':True}
            app=InfraredScreen(Path(folder));app.choose(4);app.choose(5)
            self.assertEqual(calls,[]);self.assertEqual(app.drafts,{'10:00':'screen-toggle'})
            self.assertFalse((Path(folder)/tv.FILE).exists())
            self.assertEqual(tv.assign(Path(folder),'assign',16,0,app.drafts['10:00'],program=program)['status'],'saved')
            self.assertEqual(calls,[(Path(folder),'delete',16,0,'')])
            self.assertEqual(tv.load(folder)['bindings'],{'10:00':'screen-toggle'})

    def test_invalid_selector_fails_before_storage(self):
        for button, delay in ((64, 0), (16, 1), (True, 0), (16, False)):
            with self.assertRaises(ValueError):
                tv.execute('/does/not/exist', 'set', button, delay)


if __name__ == '__main__':
    unittest.main()
