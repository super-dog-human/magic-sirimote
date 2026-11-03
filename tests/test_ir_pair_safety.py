"""A1513 fires a lone delayed IR entry immediately: never create that layout."""
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'src/native'),str(ROOT/'src/integrated')]
import tv_assignments as table
from native_manager import RuntimeSetup

class PairSafetyTests(unittest.TestCase):
    def test_tv_home_cannot_remove_guard_for_power_hold(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',1,0,'ir:7C');table.execute(d,'assign',1,2,'ir:08')
            program=Mock()
            with self.assertRaisesRegex(ValueError,'IR Hold needs an IR Press'):
                table.assign(d,'assign',1,0,'home',program=program)
            program.assert_not_called()
            self.assertEqual(table.load(d)['bindings']['01:00'],'ir:7C')

    def test_unknown_is_not_absent_and_no_implicit_guard_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            for changes in ({'01:02':'ir:08'},{'01:00':'home'},{'01:00':'none','01:02':'ir:08'}):
                with self.assertRaises(ValueError):table.plan(d,changes)
            self.assertEqual(table.plan(d,{'01:00':'ir:7C'}),[('01:00','ir:7C')])

    def test_ir_pair_is_written_press_first_and_cleared_hold_first(self):
        with tempfile.TemporaryDirectory() as d:
            program=Mock(return_value={'status':'submitted','connectionPreserved':True,'receiptSaved':True})
            for changes,expected in [({'01:02':'ir:08','01:00':'ir:7C'},[('01:00','ir:7C'),('01:02','ir:08')]),
                                     ({'01:00':'home','01:02':'none'},[('01:02','none'),('01:00','home')])]:
                planned=table.plan(d,changes);self.assertEqual(planned,expected)
                for key,value in planned:
                    button,delay=(int(s,16) for s in key.split(':'))
                    self.assertEqual(table.assign(d,'assign',button,delay,value,program=program)['status'],'saved')
            self.assertEqual(table.load(d)['bindings'],{'01:00':'home','01:02':'none'})

    def test_unsafe_save_is_rejected_before_input_drain(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());app.button_drafts={'01:00':'back','01:02':'ir:08'};app.confirm_action='save'
            with patch.object(app,'detect_tv',return_value={}),patch.object(app,'prepare_settings') as prepare:
                app.confirm_restart();prepare.assert_not_called()
            self.assertFalse(app.controls_disabled);self.assertIn('IR Hold needs',app.message)

    def test_unrelated_legacy_pair_does_not_block_safe_repair(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',1,0,'home');table.execute(d,'assign',1,2,'ir:08')
            self.assertEqual(table.plan(d,{'10:00':'ir:09'}),[('10:00','ir:09')])
            self.assertEqual(table.plan(d,{'01:00':'ir:7C'}),[('01:00','ir:7C')])

    def test_delivery_after_failed_local_save_overrides_stale_mapping(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',1,0,'ir:7C');table.execute(d,'assign',1,2,'none')
            receipt=Path(d)/'ir-operation-test.json'
            for status in ('submitted','pending','uncertain'):
                receipt.write_text(json.dumps({'status':status,'button':1,'delay':2,'action':'set','code':'08'}))
                with self.assertRaises(ValueError):table.plan(d,{'01:00':'home'})
                self.assertEqual(table.plan(d,{'01:02':'none','01:00':'home'}),[('01:02','none'),('01:00','home')])
            receipt.write_text(json.dumps({'status':'submitted','button':1,'delay':0,'action':'delete','code':None}))
            with self.assertRaises(ValueError):table.plan(d,{'01:02':'ir:08'})

    def test_failed_hold_removal_never_reaches_press_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',1,0,'ir:7C');table.execute(d,'assign',1,2,'ir:08')
            app=RuntimeSetup(Path(d),Mock())
            app.program_ir=Mock(return_value={'status':'uncertain'})
            app.start_assignment_batch({'01:00':'home','01:02':'none'})
            changes,completed,result=app.assignment_results.get(timeout=2)
            self.assertEqual(completed,[])
            app.program_ir.assert_called_once_with(Path(d),'assign',1,2,'none')
