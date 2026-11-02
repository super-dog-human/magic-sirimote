import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'native'))
import settings
from entry import Setup


class CanvasStub:
    def start_text(self): pass
    def stop_text(self): pass


class NativeSettingsTest(unittest.TestCase):
    def good(self):
        return {'schema': 1, 'remoteAddress': '02:AA:BB:CC:DD:01',
                'adapterAddress': '02:AA:BB:CC:DD:02', 'remoteName': 'TEST_REMOTE'}

    def test_normalizes_addresses_without_changing_case_sensitive_name(self):
        values = settings.validate(self.good())
        self.assertEqual(values['remoteAddress'], '02:aa:bb:cc:dd:01')
        self.assertEqual(values['remoteName'], 'TEST_REMOTE')

    def test_rejects_invalid_identities_and_extra_fields(self):
        for field, value in [('schema', True), ('remoteAddress', '01:00:00:00:00:01'),
                             ('remoteAddress', '00:00:00:00:00:00'),
                             ('remoteAddress', self.good()['adapterAddress']),
                             ('remoteName', '../a'), ('remoteName', ''), ('remoteName', 'a'*65)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                settings.validate({**self.good(), field: value})
        with self.assertRaises(ValueError):
            settings.validate({**self.good(), 'password': 'not-a-setting'})

    def test_atomic_save_load_and_invalid_save_preserves_old_value(self):
        with tempfile.TemporaryDirectory() as path:
            settings.save(path, self.good())
            before = (Path(path) / 'settings.json').read_bytes()
            self.assertEqual(os.stat(Path(path) / 'settings.json').st_mode & 0o777, 0o600)
            self.assertEqual(settings.load(path), settings.validate(self.good()))
            with self.assertRaises(ValueError):
                settings.save(path, {**self.good(), 'remoteName': ''})
            self.assertEqual((Path(path) / 'settings.json').read_bytes(), before)
            self.assertFalse(list(Path(path).glob('.settings-*')))

    def test_links_are_not_read_or_replaced(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path);target = root / 'other.json';target.write_text('leave me')
            (root / 'settings.json').symlink_to(target)
            with self.assertRaises((OSError, ValueError)):
                settings.load(root)
            with self.assertRaises(ValueError):
                settings.save(root, self.good())
            self.assertEqual(target.read_text(), 'leave me')

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as path:
            (Path(path)/'settings.json').write_text('{"schema":1,"schema":1}')
            with self.assertRaises(ValueError):
                settings.load(path)

    def test_gyro_defaults_on_for_new_and_legacy_settings(self):
        with tempfile.TemporaryDirectory() as path:
            self.assertIs(Setup(Path(path)).values['gyroEnabled'], True)
            (Path(path) / 'settings.json').write_text(json.dumps(self.good()))
            self.assertIs(settings.load(path)['gyroEnabled'], True)
            self.assertIs(Setup(Path(path)).values['gyroEnabled'], True)

    def test_gyro_toggle_requires_save_and_survives_reopen(self):
        with tempfile.TemporaryDirectory() as path:
            settings.save(path, self.good())
            app = Setup(Path(path)); canvas = CanvasStub()
            app.focus = 3; app.handle(('key', 13), canvas)
            self.assertIs(app.values['gyroEnabled'], False)
            self.assertIs(settings.load(path)['gyroEnabled'], True)
            app.choose(5, canvas)
            self.assertIn('not active', app.message)
            reopened = Setup(Path(path))
            self.assertIs(reopened.values['gyroEnabled'], False)
            self.assertEqual(reopened.values['remoteName'], self.good()['remoteName'])
            reopened.choose(3, canvas); reopened.choose(5, canvas)
            self.assertIs(settings.load(path)['gyroEnabled'], True)

    def test_invalid_gyro_values_do_not_overwrite_saved_settings(self):
        with tempfile.TemporaryDirectory() as path:
            settings.save(path, {**self.good(), 'gyroEnabled': False})
            before = (Path(path) / 'settings.json').read_bytes()
            for value in (0, 1, 'false', 'true', None, [], {}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    settings.save(path, {**self.good(), 'gyroEnabled': value})
                self.assertEqual((Path(path) / 'settings.json').read_bytes(), before)

    def test_remote_keyboard_edit_and_back_do_not_save_implicitly(self):
        with tempfile.TemporaryDirectory() as path:
            app = Setup(Path(path));canvas = CanvasStub()
            app.choose(1, canvas)
            app.choose(app.keys.index('A'), canvas)
            app.choose(app.keys.index('Case'), canvas)
            app.choose(app.keys.index('b'), canvas)
            self.assertEqual(app.values['remoteName'], 'Ab')
            app.handle(('key', 27), canvas)
            self.assertIsNone(app.editing)
            self.assertFalse((Path(path) / 'settings.json').exists())

    def test_text_input_is_bounded_and_filtered(self):
        with tempfile.TemporaryDirectory() as path:
            app = Setup(Path(path));canvas = CanvasStub();app.choose(0, canvas)
            app.handle(('text', '02:AA:BB:CC:DD:01xxxx'*10), canvas)
            self.assertEqual(app.values['remoteAddress'], '02:AA:BB:CC:DD:01')


if __name__ == '__main__':
    unittest.main()
