"""Global saves must be explicit, ordered, and never replay an uncertain write."""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/integrated'),str(ROOT/'src/native'),str(ROOT/'src')]
from native_manager import RuntimeSetup
from settings import remote_name_from_reply
import tv_assignments as table

class SaveTests(unittest.TestCase):
    def test_batch_stops_at_failure_retains_unsaved_slots_and_never_replays_success(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock())
            for button in (1,16,32): table.execute(d,'assign',button,2,'none')
            changes={'01:00':'home','10:00':'screen-toggle','20:00':'back'}
            app.button_drafts=dict(changes)
            app.program_ir=Mock(side_effect=[{'status':'saved'},{'status':'uncertain'}])
            app.start_assignment_batch(changes)
            result=app.assignment_results.get(timeout=2);app.assignment_results.put(result)
            with patch.object(app,'activate_settings') as activate:
                self.assertTrue(app.assignments_tick());activate.assert_not_called()
                self.assertFalse(app.assignments_tick())
            self.assertEqual(app.program_ir.call_count,2)
            self.assertEqual(app.button_drafts,{'10:00':'screen-toggle','20:00':'back'})
            self.assertIn('1 of 3',app.message);self.assertFalse(app.done)

    def test_batch_explains_unsent_failure_and_retains_drafts(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());app.button_drafts={'10:00':'ir:09'}
            app.program_ir=Mock(return_value={'status':'not-sent','message':'Wake the paired remote first.'})
            app.start_assignment_batch(dict(app.button_drafts))
            result=app.assignment_results.get(timeout=2);app.assignment_results.put(result)
            app.assignments_tick()
            self.assertIn('Wake the paired remote first.',app.message)
            self.assertEqual(app.button_drafts,{'10:00':'ir:09'})
            self.assertEqual(app.program_ir.call_count,1)

    def test_save_disables_and_draws_before_waiting_for_tv(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());canvas=Mock();app.confirm_action='save'
            def detect(values):
                self.assertTrue(app.controls_disabled)
                canvas.present.assert_called_once()
                self.assertEqual(app.boxes,[])
                fills=[call.args[1] for call in canvas.rectangle.call_args_list]
                self.assertEqual(len(fills),5)
                self.assertNotIn((30,113,156),fills)
                app.handle(('key',13),canvas);app.choose(6,canvas)
                self.assertIsNone(app.confirm_action);self.assertIsNone(app.infrared)
                return values
            with patch.object(app,'detect_tv',side_effect=detect), patch.object(app,'prepare_settings'):
                app.confirm_restart(canvas)
            self.assertTrue(app.controls_disabled)

    def test_failed_save_reenables_controls_and_preserves_error(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());app.confirm_action='save'
            with patch.object(app,'detect_tv',side_effect=RuntimeError('TV unavailable')):
                app.confirm_restart(Mock())
            self.assertFalse(app.controls_disabled)
            self.assertEqual(app.message,'TV unavailable')
            app.choose(6,Mock());self.assertIsNotNone(app.infrared)
            app.infrared=None;app.save_in_progress=True;app.button_drafts={'10:00':'ir:09'}
            app.assignment_results.put((dict(app.button_drafts),[],{'status':'not-sent','message':'Remote sleeping'}))
            app.assignments_tick()
            self.assertFalse(app.controls_disabled)
            self.assertEqual(app.button_drafts,{'10:00':'ir:09'})

    def test_batch_blocks_repeated_input_and_installer_until_complete(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());entered=threading.Event();release=threading.Event()
            def send(*args):entered.set();release.wait(2);return {'status':'saved'}
            table.execute(d,'assign',32,2,'none')
            app.program_ir=Mock(side_effect=send);app.button_drafts={'20:00':'back'}
            app.start_assignment_batch(dict(app.button_drafts));self.assertTrue(entered.wait(1))
            try:
                app.handle(('key',13),Mock());app.handle(('key',461),Mock())
                self.assertIsNone(app.confirm_action);self.assertFalse(app.done)
                with self.assertRaises(RuntimeError):app.apply({})
                with self.assertRaises(RuntimeError):app.stop_runtime()
            finally:release.set()
            result=app.assignment_results.get(timeout=2);app.assignment_results.put(result)
            with patch.object(app,'activate_settings') as activate:
                app.assignments_tick();activate.assert_called_once()
            self.assertFalse(app.button_drafts);app.program_ir.assert_called_once()

    def test_save_cancel_and_discard_have_no_device_side_effect(self):
        with tempfile.TemporaryDirectory() as d:
            bus=Mock();app=RuntimeSetup(Path(d),bus);canvas=Mock()
            app.button_drafts={'20:00':'none'}
            app.choose(5,canvas);app.handle(('key',461),canvas)
            self.assertEqual(app.button_drafts,{'20:00':'none'})
            app.choose(7,canvas);self.assertEqual(app.confirm_action,'discard')
            app.handle(('key',461),canvas);self.assertFalse(app.done)
            app.choose(7,canvas);app.confirm_restart()
            self.assertTrue(app.done);self.assertFalse(app.button_drafts)
            bus.request.assert_not_called();bus.tv_address.assert_not_called()

    def test_lg_back_from_matrix_picker_and_custom_retains_drafts(self):
        from ir_screen import CUSTOM
        with tempfile.TemporaryDirectory() as d:
            for key in (461,1073742094,27):
                app=RuntimeSetup(Path(d),Mock());canvas=Mock()
                app.choose(6,canvas);app.infrared.choose(0);app.infrared.choose(0)
                app.infrared.choose(2);app.infrared.choose(CUSTOM)
                app.handle(('key',key),canvas)
                self.assertIsNone(app.infrared);self.assertFalse(app.done)
                app.choose(6,canvas);self.assertEqual(app.infrared.drafts,{'20:00':'none'})

    def test_native_back_policy_is_installed_before_sdl_load(self):
        from graphics import Canvas
        def stop(*args):
            self.assertEqual(os.environ['SDL_WEBOS_ACCESS_POLICY_KEYS_BACK'],'true')
            raise RuntimeError('test stopped before native load')
        with patch.dict(os.environ,{},clear=False), patch('graphics.C.CDLL',side_effect=stop):
            with self.assertRaisesRegex(RuntimeError,'test stopped'):
                Canvas('org.magicsirimote.app')

    def test_native_webos_back_scan_without_keysym_is_decoded_once(self):
        import ctypes
        from graphics import Canvas, KeyboardEvent
        frames=[]
        for kind,scan,key,repeat in ((768,482,0,0),(768,482,0,1),(769,482,0,0),
                                     (768,484,0,0),(768,81,1073741905,0)):
            event=KeyboardEvent();event.type=kind;event.keysym.scancode=scan
            event.keysym.sym=key;event.repeat=repeat
            frames.append(bytes(event).ljust(64,b'\0'))
        canvas=Canvas.__new__(Canvas)
        def poll(buffer):
            if not frames:return 0
            ctypes.memmove(buffer,frames.pop(0),64);return 1
        canvas.poll=poll
        self.assertEqual(list(canvas.events()),[('key',461),('key',0),('key',1073741905)])

    def test_remote_identifier_uses_exact_paired_identity_only(self):
        remote='aa:bb:cc:dd:ee:10';adapter='aa:bb:cc:dd:ee:20'
        row={'address':remote.upper(),'paired':True,'name':'Remote','adapterAddress':adapter}
        reply=lambda rows:{'returnValue':True,'devices':rows}
        self.assertEqual(remote_name_from_reply(reply([row]),remote,adapter),'Remote')
        for rows in ([],[row,row],[{**row,'paired':False}],[{**row,'blocked':True}],
                     [{**row,'adapterAddress':'aa:bb:cc:dd:ee:22'}],[{**row,'name':'bad/name'}]):
            with self.assertRaises(RuntimeError):remote_name_from_reply(reply(rows),remote,adapter)
