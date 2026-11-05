import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/native'),str(ROOT/'src/integrated'),str(ROOT/'src')]
from native_manager import RuntimeSetup
import test_native_lifecycle

class CloseHomeTests(unittest.TestCase):
    def setup_app(self,d):
        bus=Mock();bus.show_home.return_value={'returnValue':True}
        bus.request.return_value={'returnValue':True}
        return RuntimeSetup(Path(d),bus),bus,Mock()

    def test_close_and_root_back_open_home_without_stopping_reception(self):
        for action in ('close','back'):
            with tempfile.TemporaryDirectory() as d:
                app,bus,canvas=self.setup_app(d)
                app.focus=7
                app.handle(('key',13 if action=='close' else 461),canvas)
                self.assertTrue(app.done);self.assertTrue(app.home_shown)
                bus.show_home.assert_called_once_with();bus.request.assert_not_called()

    def test_back_in_button_editor_returns_to_settings_not_home(self):
        with tempfile.TemporaryDirectory() as d:
            app,bus,canvas=self.setup_app(d);app.choose(6,canvas)
            app.handle(('key',461),canvas)
            self.assertIsNone(app.infrared);self.assertFalse(app.done)
            bus.show_home.assert_not_called()

    def test_unsaved_exit_waits_for_discard_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            app,bus,canvas=self.setup_app(d);app.values['gyroSensitivity']=2
            app.handle(('key',461),canvas);bus.show_home.assert_not_called()
            self.assertEqual(app.confirm_action,'discard')
            app.handle(('key',461),canvas);self.assertFalse(app.done)
            app.handle(('key',461),canvas);app.confirm_focus=1
            app.handle(('key',13),canvas)
            self.assertTrue(app.done);self.assertEqual(app.values,app.saved_values)
            bus.show_home.assert_called_once_with();bus.request.assert_not_called()

    def test_resume_confirmation_resumes_then_opens_home(self):
        with tempfile.TemporaryDirectory() as d:
            app,bus,canvas=self.setup_app(d);app.resume_after_settings=True
            app.handle(('key',461),canvas);bus.show_home.assert_not_called()
            app.confirm_focus=1;app.handle(('key',13),canvas)
            bus.request.assert_called_once_with('resume',{})
            self.assertTrue(app.done);bus.show_home.assert_called_once_with()

    def test_failed_home_request_keeps_settings_visible(self):
        with tempfile.TemporaryDirectory() as d:
            app,bus,canvas=self.setup_app(d);bus.show_home.return_value={'returnValue':False}
            app.handle(('key',461),canvas)
            self.assertFalse(app.done);self.assertFalse(app.home_shown)
            self.assertIn('Could not open Home',app.message)
            bus.show_home.assert_called_once_with()

    def test_system_close_does_not_launch_home(self):
        with tempfile.TemporaryDirectory() as d:
            app,bus,canvas=self.setup_app(d);app.handle(('close',None),canvas)
            bus.show_home.assert_not_called()

    def test_home_request_uses_fixed_application_id(self):
        bus,calls=test_native_lifecycle.NativeLifecycleTests().bus()
        self.assertTrue(bus.show_home()['returnValue'])
        self.assertEqual(calls,[(b'luna://com.webos.applicationManager/launch',b'{"id":"com.webos.app.home"}')])

if __name__=='__main__':unittest.main()
