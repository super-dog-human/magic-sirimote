import json, math, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/native'),str(ROOT/'src/integrated'),str(ROOT/'src/runtime')]
from native_manager import RuntimeSetup
from adaptive_prefix_pose import AdaptivePrefixPose
from pose_math import conjugate, pointing_angles
from test_pointer_startup import pose
from test_settings_render import DiscardingCanvas
import settings, tv_assignments as table
from ir_screen import CHOICES, InfraredScreen

class CursorControlsTests(unittest.TestCase):
    def test_slider_is_bounded_and_does_not_save_or_restart(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());canvas=DiscardingCanvas();app.draw(canvas);app.focus=4
            self.assertEqual(app.values['gyroSensitivity'],3)
            for _ in range(8):app.handle(('key',1073741903),canvas)
            self.assertEqual(app.values['gyroSensitivity'],5)
            for _ in range(8):app.handle(('key',1073741904),canvas)
            self.assertEqual(app.values['gyroSensitivity'],1)
            app.handle(('click',(420,372)),canvas)
            self.assertEqual(app.values['gyroSensitivity'],3)
            app.bus.request.assert_not_called();self.assertEqual(list(Path(d).iterdir()),[])
            app.handle(('key',1073741905),canvas);self.assertEqual(app.focus,8)

    def test_sensitivity_defaults_validation_and_roundtrip(self):
        values={'schema':1,'remoteAddress':'aa:bb:cc:dd:ee:10','adapterAddress':'aa:bb:cc:dd:ee:20','remoteName':'Remote'}
        self.assertEqual(settings.validate(values)['gyroSensitivity'],3)
        for level in (True,False,0,6,3.0,'3',None):
            with self.assertRaises(ValueError):settings.validate({**values,'gyroSensitivity':level})
        with tempfile.TemporaryDirectory() as d:
            settings.save(d,{**values,'gyroSensitivity':5})
            self.assertEqual(RuntimeSetup(Path(d),Mock()).values['gyroSensitivity'],5)

    def test_equal_axis_gains_five_levels_and_unchanged_response_timing(self):
        totals=[];first=[]
        for level in range(1,6):
            p=AdaptivePrefixPose(level);out=[];when=[]
            self.assertEqual(p.AXIS_GAINS[0],p.AXIS_GAINS[1]);self.assertEqual(p.PERIOD,.020)
            for i in range(150):
                p.feed(pose(max(0,i-30)*.004),i*.01);delta=p.tick(i*.01)
                if delta is not None:out.append(abs(delta[0]));when.append(i*.01)
            totals.append(sum(out));first.append(when[0])
        self.assertEqual(totals,sorted(set(totals)))
        self.assertLessEqual(max(first)-min(first),.04)
        self.assertEqual(AdaptivePrefixPose(3).AXIS_GAINS,(1453.5,1453.5))

    def test_reset_only_drains_and_resumes_without_saving_or_ir(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());canvas=Mock()
            app.bus.request.return_value={'returnValue':True}
            app.choose(8,canvas);self.assertEqual(app.confirm_action,'recenter')
            with patch.object(app,'persist_device') as persist,patch.object(app,'program_ir') as ir:
                app.confirm_restart(canvas);self.assertTrue(app.controls_disabled)
                app.bus.request.return_value={'returnValue':True,'cleanStop':True,'processes':{'legacy':[]}}
                self.assertTrue(app.settings_tick(canvas));self.assertTrue(app.done)
                persist.assert_not_called();ir.assert_not_called()
            self.assertEqual([c.args[0] for c in app.bus.request.call_args_list],['drain','status','resume'])
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_reset_preserves_unsaved_edits_and_cancel_has_no_effect(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());app.choose(8,Mock());app.handle(('key',461),Mock())
            app.bus.request.assert_not_called();self.assertFalse(app.done)
            app.button_drafts={'10:00':'ir:09'};app.choose(8,Mock())
            self.assertIsNone(app.confirm_action);self.assertEqual(app.button_drafts,{'10:00':'ir:09'})

    def test_new_receiver_reference_replaces_tilted_reference(self):
        tilted=AdaptivePrefixPose();flat=AdaptivePrefixPose()
        sample=pose();sample['orientation3']=(0.,math.sin(.5),0.)
        for i in range(30):tilted.feed(sample,i*.01);flat.feed(pose(),i*.01)
        self.assertNotEqual(tilted.reference_inverse,flat.reference_inverse)
        self.assertEqual(flat.reference_inverse,(0.,0.,0.,1.))

class FullSaveTests(unittest.TestCase):
    def test_only_ir_home_is_selectable_and_legacy_home_is_migrated(self):
        self.assertNotIn('home',[v for _,v in CHOICES]);self.assertIn(('Home (IR)','ir:7C'),CHOICES)
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',1,0,'home');table.execute(d,'assign',1,2,'ir:08')
            full=table.displayed_bindings(d,{})
            self.assertEqual(full['01:00'],'ir:7C');self.assertEqual(full['01:02'],'ir:08')
            table.plan(d,full)

    def test_full_save_includes_unchanged_values_and_omits_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            for b,t,v in ((1,0,'ir:7C'),(1,2,'ir:08'),(16,0,'ir:09'),(32,0,'back'),(32,2,'none')):
                table.execute(d,'assign',b,t,v)
            full=table.displayed_bindings(d,{'08:00':'pause'})
            self.assertEqual(full['01:00'],'ir:7C');self.assertEqual(full['01:02'],'ir:08')
            self.assertEqual(full['10:00'],'ir:09');self.assertEqual(full['08:00'],'pause')
            self.assertNotIn('02:00',full);self.assertNotIn('10:02',full)
            self.assertEqual(full['08:02'],'pause')
            table.plan(d,full)

class PreferenceRuntimeTests(unittest.TestCase):
    def test_saved_preferences_reach_router_without_bypassing_sensor_gate(self):
        from prefix_output_candidate import PrefixOutputCandidate
        import runtime_device
        with patch.object(runtime_device,'_cursor',(False,5)):
            receiver=PrefixOutputCandidate(Mock(),clock=lambda:0.,sensor_input_verified=True)
            self.assertFalse(receiver.router.motion_enabled)
            self.assertEqual(receiver.router.pose.AXIS_GAINS,(2180.25,2180.25))
            receiver.bind(1);receiver.feed_raw(1,b'\xfc\x00\x00')
            self.assertFalse(receiver.router.motion_enabled)
        with patch.object(runtime_device,'_cursor',(True,1)):
            receiver=PrefixOutputCandidate(Mock(),clock=lambda:0.,sensor_input_verified=False)
            receiver.bind(1);receiver.feed_raw(1,b'\xfc\x00\x00')
            self.assertFalse(receiver.router.motion_enabled)
