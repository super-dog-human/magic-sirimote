"""Only explicit edits (and required same-button safety cleanup) reach IR."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'src/native'),str(ROOT/'src/integrated')]
import tv_assignments as table
from native_manager import RuntimeSetup

class ChangedAssignments(unittest.TestCase):
    def test_no_edits_never_reconcile_remote_slots(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',1,0,'ir:7C');table.execute(d,'assign',1,2,'ir:08')
            with patch.object(table,'ir_knowledge',side_effect=AssertionError('unneeded IR inspection')):
                self.assertEqual(table.changed_bindings(d,{}),{})
            app=RuntimeSetup(Path(d),Mock());app.confirm_action='save'
            with patch.object(app,'detect_tv',return_value={}),patch.object(app,'prepare_settings'):
                app.confirm_restart()
            self.assertEqual(app.pending_assignments,{})

    def test_only_changed_volume_button_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            for b,delay,code in ((1,0,'ir:7C'),(1,2,'ir:08'),(2,0,'ir:02')):
                table.execute(d,'assign',b,delay,code)
            changes=table.changed_bindings(d,{'02:00':'ir:03'})
            self.assertEqual(changes,{'02:00':'ir:03'})
            program=Mock(return_value={'status':'submitted','connectionPreserved':True,'receiptSaved':True})
            table.assign(d,'assign',2,0,'ir:03',program=program)
            program.assert_called_once_with(d,'set',2,0,'03')
            self.assertEqual(table.load(d)['bindings'],{'01:00':'ir:7C','01:02':'ir:08','02:00':'ir:03'})

    def test_unchanged_explicit_value_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',2,0,'ir:02')
            self.assertEqual(table.changed_bindings(d,{'02:00':'ir:02'}),{})
            program=Mock()
            self.assertEqual(table.assign(d,'assign',2,0,'ir:02',program=program)['status'],'saved')
            program.assert_not_called()

    def test_tv_to_tv_change_needs_no_remote_write(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',16,0,'screen-toggle');table.execute(d,'assign',16,2,'none')
            self.assertEqual(table.changed_bindings(d,{'10:00':'playpause'}),{'10:00':'playpause'})
            program=Mock()
            self.assertEqual(table.assign(d,'assign',16,0,'playpause',program=program)['status'],'saved')
            program.assert_not_called()
            self.assertEqual(table.load(d)['bindings']['10:00'],'playpause')

    def test_unknown_remote_contents_are_not_treated_as_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(table.changed_bindings(d,{'10:00':'none'}),{'10:00':'none','10:02':'none'})
            self.assertEqual(table.changed_bindings(d,{'02:00':'ir:02'}),{'02:00':'ir:02'})
            table.execute(d,'assign',16,0,'screen-toggle');table.execute(d,'assign',16,2,'none')
            (Path(d)/'ir-operation-uncertain.json').write_text(json.dumps({'status':'uncertain','action':'set','button':16,'delay':0,'code':'09'}))
            self.assertEqual(table.changed_bindings(d,{'10:00':'screen-toggle'}),{'10:00':'screen-toggle'})
            program=Mock(return_value={'status':'submitted','connectionPreserved':True,'receiptSaved':True})
            table.assign(d,'assign',16,0,'screen-toggle',program=program)
            program.assert_called_once_with(d,'delete',16,0,'')

    def test_confirmed_write_with_failed_local_save_is_not_resent(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',2,0,'ir:02')
            (Path(d)/'ir-operation-confirmed.json').write_text(json.dumps({'status':'submitted','action':'set','button':2,'delay':0,'code':'03'}))
            self.assertEqual(table.changed_bindings(d,{'02:00':'ir:03'}),{'02:00':'ir:03'})
            program=Mock()
            self.assertEqual(table.assign(d,'assign',2,0,'ir:03',program=program)['status'],'saved')
            program.assert_not_called()
            self.assertEqual(table.load(d)['bindings']['02:00'],'ir:03')

if __name__=='__main__':unittest.main()
